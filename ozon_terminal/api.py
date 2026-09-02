from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .collector import JobRunner, search_one_keyword
from .cookies import CookieVault
from .database import Database
from .exporter import to_csv, to_json
from .browser_proxy import BrowserProxy


DIFY_BEARER_SCHEME = "Bearer "
DIFY_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="缺少或无效的 Dify 鉴权密钥",
    headers={"WWW-Authenticate": "Bearer"},
)


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
    category: str | None = Field(default=None, max_length=64)
    price_min: int | None = Field(default=None, ge=0, le=10_000_000)
    price_max: int | None = Field(default=None, ge=0, le=10_000_000)
    sort: Literal["price", "price_desc", "relevance", "newest"] | None = None
    with_categories: bool = True

    @field_validator("price_max")
    @classmethod
    def price_bounds(cls, value: int | None, info) -> int | None:
        if value is None:
            return value
        minimum = info.data.get("price_min")
        if minimum is not None and value < minimum:
            raise ValueError("price_max 不能小于 price_min")
        return value


class DifyBatchRequest(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=10)
    pages: int = Field(default=3, ge=1, le=20)
    target: int = Field(default=120, ge=1, le=500)
    preview: int = Field(default=120, ge=1, le=500)
    category: str | None = Field(default=None, max_length=64)
    price_min: int | None = Field(default=None, ge=0, le=10_000_000)
    price_max: int | None = Field(default=None, ge=0, le=10_000_000)
    sort: Literal["price", "price_desc", "relevance", "newest"] | None = None
    with_categories: bool = True

    @field_validator("price_max")
    @classmethod
    def price_bounds(cls, value: int | None, info) -> int | None:
        if value is None:
            return value
        minimum = info.data.get("price_min")
        if minimum is not None and value < minimum:
            raise ValueError("price_max 不能小于 price_min")
        return value

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            if not isinstance(raw, str):
                continue
            stripped = raw.strip()
            if not stripped or len(stripped) > 120:
                continue
            if stripped in seen:
                continue
            seen.add(stripped)
            cleaned.append(stripped)
        if not cleaned:
            raise ValueError("keywords 不能为空")
        return cleaned

    @field_validator("preview")
    @classmethod
    def preview_within_target(cls, value: int, info) -> int:
        target = info.data.get("target")
        if target is not None and value > target:
            return target
        return value


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
                category=spec.category,
                price_min=spec.price_min,
                price_max=spec.price_max,
                sort=spec.sort,
                with_categories=spec.with_categories,
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

    def _require_dify_key(request: Request) -> None:
        expected = os.getenv("OZON_DIFY_API_KEY")
        if not expected:
            raise DIFY_UNAUTHORIZED
        header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if not header.startswith(DIFY_BEARER_SCHEME):
            raise DIFY_UNAUTHORIZED
        token = header[len(DIFY_BEARER_SCHEME):].strip()
        if not token or token != expected:
            raise DIFY_UNAUTHORIZED

    @app.post(
        "/api/dify/search",
        dependencies=[Depends(_require_dify_key)],
        openapi_extra={},
    )
    async def dify_search(spec: DifyBatchRequest):
        if not vault.ready:
            raise HTTPException(409, "请先在网页端导入 Chrome Cookie 后再调用 Dify 搜索")
        cookies = vault.snapshot()
        results: list[dict[str, Any]] = []
        for keyword in spec.keywords:
            try:
                result = await search_one_keyword(
                    keyword,
                    cookies,
                    spec.target,
                    spec.preview,
                    False,
                    runner._client_factory,
                    None,
                    max_pages=spec.pages,
                    category=spec.category,
                    price_min=spec.price_min,
                    price_max=spec.price_max,
                    sort=spec.sort,
                    with_categories=spec.with_categories,
                )
            except RuntimeError as exc:
                raise HTTPException(400, f"{keyword}: {exc}") from exc
            results.append({
                "keyword": result["keyword"],
                "requested_pages": result["requested_pages"],
                "pages": result["pages"],
                "unique": result["unique"],
                "returned": result["returned"],
                "items": result["items"],
                "categories": result["categories"],
            })
        return {"count": len(results), "results": results}

    @app.get("/openapi/dify.json")
    def dify_openapi(_: None = Depends(_require_dify_key)):
        spec = app.openapi()
        operations = {
            path: {
                method: operation
                for method, operation in path_item.items()
                if isinstance(operation, dict)
            }
            for path, path_item in spec.get("paths", {}).items()
            if path.startswith("/api/dify")
        }
        components = {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "API Key",
                }
            }
        }
        schemas = spec.get("components", {}).get("schemas", {})
        dify_schema = schemas.get("DifyBatchRequest")
        if not dify_schema:
            dify_schema = {
                "type": "object",
                "required": ["keywords"],
                "properties": {
                    "keywords": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10},
                    "pages": {"type": "integer", "default": 3, "minimum": 1, "maximum": 20},
                    "target": {"type": "integer", "default": 120, "minimum": 1, "maximum": 500},
                    "preview": {"type": "integer", "default": 120, "minimum": 1, "maximum": 500},
                    "category": {"type": "string", "description": "Ozon 类目数字 ID（如 7500 表示服装鞋与配饰）"},
                    "price_min": {"type": "integer", "minimum": 0, "maximum": 10000000, "description": "最低价格（₽）"},
                    "price_max": {"type": "integer", "minimum": 0, "maximum": 10000000, "description": "最高价格（₽），不能小于 price_min"},
                    "sort": {"type": "string", "enum": ["price", "price_desc", "relevance", "newest"], "description": "Ozon 排序方式"},
                    "with_categories": {"type": "boolean", "default": True, "description": "是否在响应中返回该关键词命中的 Ozon 类目列表，便于二次调用锁定类目"},
                },
            }
        dify_schemas = {
            "DifyBatchRequest": dify_schema,
            "DifySearchResultItem": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "price": {"type": "string"},
                    "original_price": {"type": "string"},
                    "discount": {"type": "string"},
                    "rating": {"type": "string"},
                    "reviews": {"type": "string"},
                    "stock": {"type": "string"},
                    "link": {"type": "string"},
                    "main_image": {"type": "string"},
                    "images": {"type": "array", "items": {"type": "string"}},
                },
            },
            "DifyCategory": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Ozon 类目 ID"},
                    "name": {"type": "string", "description": "Ozon 俄语/俄哈语原名"},
                    "level": {"type": "integer", "nullable": True, "description": "层级：0=一级，1=二级…"},
                    "url": {"type": "string", "description": "Ozon 类目页 URL"},
                },
            },
            "DifyKeywordResult": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "requested_pages": {"type": "integer"},
                    "pages": {"type": "integer"},
                    "unique": {"type": "integer"},
                    "returned": {"type": "integer"},
                    "items": {"type": "array", "items": {"$ref": "#/components/schemas/DifySearchResultItem"}},
                    "categories": {"type": "array", "items": {"$ref": "#/components/schemas/DifyCategory"}, "description": "该关键词命中的 Ozon 类目列表（最多 3 项）"},
                },
            },
            "DifySearchResponse": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "results": {"type": "array", "items": {"$ref": "#/components/schemas/DifyKeywordResult"}},
                },
            },
        }
        dify_security = [{"BearerAuth": []}]
        return {
            "openapi": "3.0.3",
            "info": {
                "title": "Ozon Search API for Dify",
                "version": "0.1.0",
                "description": "供 Dify 智能体调用的 Ozon 关键词搜索接口。需通过 Bearer 鉴权，并保证后端已注入 Ozon Cookie。",
            },
            "servers": [{"url": "https://yidong.dianleida.net:21997"}],
            "paths": {
                path: {
                    **path_item,
                    **{method: {**operation, "security": dify_security} for method, operation in path_item.items()},
                }
                for path, path_item in operations.items()
            },
            "components": {"schemas": dify_schemas, **components},
        }

    static = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


app = create_app()
