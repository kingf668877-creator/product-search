from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

import httpx

from .cookies import CookieVault
from .database import Database

log = logging.getLogger(__name__)
ClientFactory = Callable[[httpx.Cookies], Awaitable[httpx.AsyncClient] | httpx.AsyncClient]

OZON_BASE = "https://www.ozon.kz"
OZON_ENTRYPOINT = f"{OZON_BASE}/api/entrypoint-api.bx/page/json/v2"
OZON_HOST_KZ = "ozon.kz"


def extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return [{"value": payload}]
    for key in ("items", "results", "products", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = extract_items(value)
            if nested != [value]:
                return nested
    return [payload]


def extract_next_page(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("nextPage", "next_page"):
        value = payload.get(key)
        if value:
            return str(value)
    for key in ("pagination", "paging", "data"):
        if isinstance(payload.get(key), dict):
            found = extract_next_page(payload[key])
            if found:
                return found
    return None


def next_request(endpoint: str, method: str, base_request: dict[str, Any], token: str | None) -> tuple[str, dict[str, Any]]:
    request = dict(base_request)
    if not token:
        return endpoint, request
    if token.startswith("http://") or token.startswith("https://") or token.startswith("/"):
        return urljoin(endpoint, token), request
    if method == "GET":
        request["page"] = token
        return endpoint, request
    request["page"] = token
    return endpoint, request


class JobRunner:
    def __init__(self, db: Database, cookies: CookieVault, client_factory: Callable | None = None) -> None:
        self.db, self.cookies = db, cookies
        self._tasks: dict[str, asyncio.Task] = {}
        self._client_factory = client_factory

    async def start(self, job_id: str) -> None:
        if job_id in self._tasks and not self._tasks[job_id].done():
            return
        self.db.set_status(job_id, "running")
        task = asyncio.create_task(self._run(job_id), name=f"ozon-job-{job_id}")
        self._tasks[job_id] = task

    def request_pause(self, job_id: str) -> None:
        job = self.db.get_job(job_id)
        if job["status"] in {"pending", "running"}:
            self.db.set_status(job_id, "pausing")

    async def resume(self, job_id: str) -> None:
        if self.db.get_job(job_id)["status"] not in {"paused", "failed", "pending"}:
            raise ValueError("任务当前不可继续")
        await self.start(job_id)

    def cancel(self, job_id: str) -> None:
        job = self.db.get_job(job_id)
        if job["status"] not in {"completed", "cancelled"}:
            self.db.set_status(job_id, "cancelling")

    async def wait(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task:
            await task

    async def _client(self, cookies: httpx.Cookies) -> httpx.AsyncClient:
        if self._client_factory:
            client = self._client_factory(cookies)
            return await client if hasattr(client, "__await__") else client
        return httpx.AsyncClient(
            cookies=cookies,
            timeout=httpx.Timeout(30),
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 OzonDataTerminal/0.1"},
        )

    async def _run(self, job_id: str) -> None:
        try:
            job = self.db.get_job(job_id)
            page_no, token = job["pages"], job["next_page"]
            endpoint, method, body = job["endpoint"], job["method"], job["request"]
            cookies = self.cookies.snapshot()
            client = await self._client(cookies)
            async with client:
                while True:
                    status = self.db.get_job(job_id)["status"]
                    if status in {"pausing", "cancelling"}:
                        self.db.set_status(job_id, "paused" if status == "pausing" else "cancelled")
                        return
                    url, request = next_request(endpoint, method, body, token)
                    response = await client.request(method, url, params=request if method == "GET" else None, json=request if method != "GET" else None)
                    response.raise_for_status()
                    payload = response.json()
                    page_no += 1
                    token = extract_next_page(payload)
                    self.db.save_page(job_id, page_no, extract_items(payload), token)
                    if not token:
                        self.db.set_status(job_id, "completed")
                        return
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            self.db.set_status(job_id, "paused", "执行器已停止")
            raise
        except Exception as exc:
            log.error("Job %s failed: %s", job_id, type(exc).__name__)
            self.db.set_status(job_id, "failed", f"{type(exc).__name__}: {exc}")


def _extract_tile_grid(payload: Any) -> list[Any]:
    states = payload.get("widgetStates") if isinstance(payload, dict) else None
    if not isinstance(states, dict):
        return []
    for key, raw in states.items():
        if not key.startswith("tileGridDesktop"):
            continue
        try:
            widget = json.loads(raw)
        except (TypeError, ValueError):
            continue
        items = widget.get("items") if isinstance(widget, dict) else None
        if isinstance(items, list):
            return items
    return []


def _flatten_item(item: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"id": item.get("id") or item.get("sku")}
    out["title"] = None
    out["price"] = None
    out["original_price"] = None
    out["discount"] = None
    out["rating"] = None
    out["reviews"] = None
    out["stock"] = None
    out["link"] = item.get("action", {}).get("link") if isinstance(item.get("action"), dict) else None
    images = item.get("tileImage", {}).get("items", []) if isinstance(item.get("tileImage"), dict) else []
    out["main_image"] = images[0].get("image", {}).get("link") if images else None
    out["images"] = [img.get("image", {}).get("link") for img in images if isinstance(img, dict)]
    states = item.get("mainState") if isinstance(item.get("mainState"), list) else []
    # 合并所有 priceV2：取第一个非空 PRICE 作为现价，最后一个 ORIGINAL_PRICE 作为原价
    for state in states:
        if not isinstance(state, dict):
            continue
        kind = state.get("type")
        if not kind:
            # 兼容没有 type 字段：取第一个以已知 kind 命名的子键
            for k in state.keys():
                if k in ("priceV2", "textDS", "labelListV2", "atom"):
                    kind = k
                    break
        body = state.get(kind) if kind else None
        if not isinstance(body, dict):
            continue
        if kind == "priceV2":
            prices = body.get("price") or []
            for p in prices:
                if not isinstance(p, dict):
                    continue
                style = p.get("textStyle")
                text = p.get("text")
                if style == "PRICE" and out["price"] is None:
                    out["price"] = text
                elif style == "ORIGINAL_PRICE":
                    out["original_price"] = text
            if body.get("discount") and out["discount"] is None:
                out["discount"] = body.get("discount")
        elif kind == "labelListV2":
            for label in body.get("items", []) if isinstance(body.get("items"), list) else []:
                if not isinstance(label, dict):
                    continue
                text = label.get("text")
                if isinstance(text, dict) and text.get("text"):
                    value = str(text["text"]).strip()
                    if out["rating"] is None and re_fullmatch(r"\d+(\.\d+)?", value):
                        out["rating"] = value
                    elif out["rating"] is not None and out["reviews"] is None:
                        out["reviews"] = value
        elif kind == "textDS":
            # textDS 结构：{"type":"textDS","textDS":{"text":"..."},"id":"name"|None}
            text = body.get("text") if isinstance(body, dict) else None
            ref = state.get("id") if isinstance(state, dict) else None
            if ref == "name" and text:
                out["title"] = text
            elif text and out["stock"] is None and any(kw in str(text) for kw in ("осталос", "штук", "осталось", "kaldı", "kald")):
                out["stock"] = text
    return out


def re_fullmatch(pattern: str, value: str) -> bool:
    return bool(re.fullmatch(pattern, value))


async def search_one_keyword(
    keyword: str,
    cookies: httpx.Cookies | None,
    target: int = 2000,
    preview: int = 120,
    detail: bool = False,
    client_factory: Callable | None = None,
    page_fetcher: Callable | None = None,
) -> dict[str, Any]:
    """一次性顺序翻页搜索一个关键词，返回商品预览。"""
    if not keyword or not keyword.strip():
        raise RuntimeError("关键词不能为空")
    params: dict[str, Any] = {"url": f"/search/?deny_category_prediction=true&from_global=true&text={quote(keyword.strip())}"}
    unique_items: dict[str, dict[str, Any]] = {}
    pages = 0

    async def fetch_via_browser(url_path: str) -> dict[str, Any]:
        if page_fetcher is None:
            raise RuntimeError("缺少浏览器代理：请先在前端网页中通过浏览器中转接口请求 Ozon")
        return await page_fetcher(url_path)

    if page_fetcher is not None:
        while True:
            try:
                payload = await fetch_via_browser(params["url"])
            except RuntimeError as exc:
                raise
            pages += 1
            tile_items = _extract_tile_grid(payload)
            for raw in tile_items:
                flat = _flatten_item(raw)
                sku = str(flat.get("id") or "")
                if sku and sku not in unique_items:
                    unique_items[sku] = flat
            next_page = extract_next_page(payload)
            if not next_page or len(unique_items) >= target:
                break
            if isinstance(next_page, str) and next_page.startswith("/"):
                params = {"url": next_page}
            else:
                break
        items = list(unique_items.values())[:max(1, preview)]
        return {"keyword": keyword, "pages": pages, "unique": len(unique_items), "returned": len(items), "items": items}

    if cookies is None:
        raise RuntimeError("需要先导入 Cookie 才能直连 Ozon")

    if client_factory is None:
        client_cm = httpx.AsyncClient(cookies=cookies, timeout=httpx.Timeout(20), follow_redirects=True)
    else:
        produced = client_factory(cookies)
        if hasattr(produced, "__await__"):
            produced = await produced
        if not isinstance(produced, httpx.AsyncClient):
            raise RuntimeError("client_factory 必须返回 httpx.AsyncClient")
        client_cm = produced
    async with client_cm as client:
        while True:
            try:
                response = await client.get(OZON_ENTRYPOINT, params=params)
            except httpx.HTTPError as exc:
                raise RuntimeError(f"调用 Ozon 接口失败：{type(exc).__name__}") from exc
            if response.status_code in {403, 429}:
                raise RuntimeError(f"Ozon 返回 {response.status_code}，可能触发风控，请降低频率或暂停采集")
            response.raise_for_status()
            payload = response.json()
            pages += 1
            tile_items = _extract_tile_grid(payload)
            for raw in tile_items:
                flat = _flatten_item(raw)
                sku = str(flat.get("id") or "")
                if sku and sku not in unique_items:
                    unique_items[sku] = flat
            next_page = extract_next_page(payload)
            if not next_page or len(unique_items) >= target:
                break
            if isinstance(next_page, str) and next_page.startswith("/"):
                params = {"url": next_page}
            else:
                break
            await asyncio.sleep(0)
    items = list(unique_items.values())[:max(1, preview)]
    return {
        "keyword": keyword,
        "pages": pages,
        "unique": len(unique_items),
        "returned": len(items),
        "items": items,
    }


async def _ensure_client(coro_or_client, headers: dict[str, str], cookies: httpx.Cookies) -> httpx.AsyncClient:
    if hasattr(coro_or_client, "__await__"):
        client = await coro_or_client
    else:
        client = coro_or_client
    if headers and not client.headers.get("User-Agent"):
        client.headers.update(headers)
    if cookies and not client.cookies.jar:
        client.cookies.update(cookies)
    return client
