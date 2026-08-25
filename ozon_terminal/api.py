from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .collector import JobRunner, search_one_keyword
from .cookies import CookieVault
from .database import Database
from .exporter import to_csv, to_json
from .browser_proxy import BrowserProxy


class JobCreate(BaseModel):
    endpoint: str
    method: Literal["GET", "POST"] = "POST"
    request: dict[str, Any] = Field(default_factory=dict)
    auto_start: bool = True

    @field_validator("endpoint")
    @classmethod
    def ozon_only(cls, value: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host == "ozon.ru" or host.endswith(".ozon.ru")):
            raise ValueError("仅允许 https://ozon.ru 及其子域名")
        return value


class KeywordRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=120)
    target: int = Field(default=2000, ge=1, le=2000)
    preview: int = Field(default=120, ge=1, le=500)
    pages: int | None = Field(default=None, ge=1, le=100)
    detail: bool = False
    fetcher: Literal["server", "browser"] = "server"


class BrowserCookiePayload(BaseModel):
    domain: str = ".ozon.kz"
    cookies: list[dict[str, Any]]


class CookieHeaderPayload(BaseModel):
    header: str
    domain: str = ".ozon.kz"


def create_app(db_path: str | Path | None = None, client_factory=None) -> FastAPI:
    db = Database(db_path or os.getenv("OZON_TERMINAL_DB", "ozon_terminal.db"))
    vault = CookieVault()
    vault.load_from_db(db)  # 从 SQLite 恢复历史 Cookie
    runner = JobRunner(db, vault, client_factory)
    browser_proxy = BrowserProxy()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        vault.clear()
        db.close()

    app = FastAPI(title="Ozon Data Terminal", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.db = db
    app.state.cookies = vault
    app.state.runner = runner
    app.state.browser_proxy = browser_proxy

    @app.get("/api/health")
    def health():
        return {"ok": True, "cookie_ready": vault.ready, "cookie_count": vault.count}

    @app.post("/api/cookies/import")
    def import_cookies(domain: str = ".ozon.ru"):
        try:
            count = vault.import_chrome(domain)
            return {"ready": True, "count": count}
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/cookies")
    def clear_cookies():
        vault.clear()
        db.clear_cookie_header()
        return {"ready": False}

    @app.post("/api/cookies/upload")
    def upload_cookies(payload: BrowserCookiePayload):
        try:
            count = vault.load_from_browser(payload.cookies, payload.domain)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ready": True, "count": count}

    @app.post("/api/cookies/header")
    def upload_header(payload: CookieHeaderPayload):
        try:
            count = vault.load_from_header(payload.header, payload.domain)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        vault.save_to_db(db)
        return {"ready": True, "count": count}

    @app.get("/api/jobs")
    def list_jobs():
        return db.list_jobs()

    @app.post("/api/jobs", status_code=201)
    async def create_job(spec: JobCreate):
        if spec.auto_start and not vault.ready:
            raise HTTPException(409, "请先导入 Chrome Cookie")
        job = db.create_job(spec.endpoint, spec.method, spec.request)
        if spec.auto_start:
            await runner.start(job["id"])
        return db.get_job(job["id"])

    def job_or_404(job_id: str):
        try:
            return db.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return job_or_404(job_id)

    @app.post("/api/jobs/{job_id}/pause")
    def pause(job_id: str):
        job_or_404(job_id)
        runner.request_pause(job_id)
        return db.get_job(job_id)

    @app.post("/api/jobs/{job_id}/resume")
    async def resume(job_id: str):
        job_or_404(job_id)
        if not vault.ready:
            raise HTTPException(409, "应用重启或 Cookie 已清除，请重新导入")
        try:
            await runner.resume(job_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return db.get_job(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        job_or_404(job_id)
        runner.cancel(job_id)
        return db.get_job(job_id)

    @app.get("/api/jobs/{job_id}/export.{fmt}")
    def export(job_id: str, fmt: Literal["csv", "json"]):
        job_or_404(job_id)
        content = to_csv(db.records(job_id)) if fmt == "csv" else to_json(db.records(job_id))
        media = "text/csv; charset=utf-8" if fmt == "csv" else "application/json; charset=utf-8"
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{job_id}.{fmt}"'})

    @app.post("/api/search")
    async def search(spec: KeywordRequest):
        try:
            page_fetcher = None
            cookies = None
            if spec.fetcher == "browser":
                async def _browser(path: str) -> dict[str, Any]:
                    payload = await app.state.browser_proxy.get(path, timeout=30)
                    return payload
                page_fetcher = _browser
            else:
                if not vault.ready:
                    raise HTTPException(409, "请先导入 Chrome Cookie")
                cookies = vault.snapshot()
            result = await search_one_keyword(
                spec.keyword,
                cookies,
                spec.target,
                spec.preview,
                spec.detail,
                runner._client_factory,
                page_fetcher,
                max_pages=spec.pages,
            )
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        return result

    @app.post("/api/fetch")
    async def proxy_fetch(request: Request):
        try:
            data = json.loads((await request.body()).decode() or "{}")
        except Exception:
            data = {}
        if not isinstance(data, dict) or "payload" not in data or "path" not in data:
            raise HTTPException(400, "浏览器代理请求缺少 payload/path")
        path = str(data["path"])
        waiter = browser_proxy.consume(path)
        if waiter is None or waiter.done():
            return {"status": "ignored", "path": path}
        waiter.set_result(data["payload"])
        return {"status": "accepted", "path": path}

    @app.get("/api/proxy/next")
    async def proxy_next():
        # 返回当前等待浏览器 fetch 的页面路径；前端可轮询此接口。
        for path, fut in browser_proxy._waiters.items():
            if not fut.done():
                return {"path": path}
        return {"path": None}

    static = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


app = create_app()
