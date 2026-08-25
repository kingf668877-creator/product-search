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


def _repair_mojibake(value: Any) -> Any:
    if isinstance(value, str):
        for _ in range(3):
            if not any(marker in value for marker in ("Ã", "Ð", "Ñ", "Â", "å", "¤")):
                break
            try:
                repaired = value.encode("latin-1").decode("utf-8")
            except UnicodeDecodeError:
                break
            if repaired == value:
                break
            value = repaired
        return value
    if isinstance(value, list):
        return [_repair_mojibake(item) for item in value]
    if isinstance(value, dict):
        return {key: _repair_mojibake(item) for key, item in value.items()}
    return value


KEYWORD_EXPANSIONS = {
    "男士": ("мужской", "мужчина"),
    "外套": ("куртка", "пальто", "верхняя одежда"),
}


def _decode_json_bytes(content: bytes) -> Any:
    texts = []
    for encoding in ("utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            if encoding == "latin-1":
                text = text.encode("latin-1").decode("utf-8")
            texts.append(text)
        except UnicodeDecodeError:
            continue
    last_error: UnicodeDecodeError | json.JSONDecodeError | None = None
    parsed: list[tuple[str, Any]] = []
    for text in texts:
        try:
            parsed.append((text, json.loads(text)))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc
    if parsed:
        return _repair_mojibake(parsed[0][1])
    raise json.JSONDecodeError("无法解析 Ozon JSON 响应", texts[-1] if texts else "", 0) from last_error


def _decode_json_response(response: httpx.Response) -> Any:
    content_type = (response.headers.get("content-type") or "").lower()
    if "application/json" in content_type and "charset=" not in content_type:
        response.encoding = "utf-8"
    return _decode_json_bytes(response.content)


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
                    payload = _decode_json_response(response)
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


def expand_keywords(keyword: str) -> list[str]:
    value = keyword.strip()
    replacements = [(chinese, russian_terms) for chinese, russian_terms in KEYWORD_EXPANSIONS.items() if chinese in value]
    if not replacements:
        return [value]
    variants = [value]
    for chinese, russian_terms in replacements:
        variants = [variant.replace(chinese, russian) for variant in variants for russian in russian_terms]
    return list(dict.fromkeys([value, *variants]))


def _item_relevance(item: dict[str, Any], terms: list[str]) -> tuple[int, int]:
    haystack = " ".join(str(item.get(key) or "") for key in ("title", "link"))
    lowered = haystack.casefold()
    matches = sum(1 for term in terms if term.casefold() in lowered)
    return (-matches, terms.index(next((term for term in terms if term.casefold() in lowered), terms[0])))


async def _search_term(
    term: str,
    cookies: httpx.Cookies | None,
    target: int,
    client: httpx.AsyncClient | None = None,
    page_fetcher: Callable | None = None,
    max_pages: int | None = None,
) -> tuple[int, dict[str, dict[str, Any]]]:
    params: dict[str, Any] = {"url": f"/search/?deny_category_prediction=true&from_global=true&text={quote(term)}"}
    unique_items: dict[str, dict[str, Any]] = {}
    pages = 0

    async def consume(payload: Any) -> str | None:
        nonlocal pages
        pages += 1
        for raw in _extract_tile_grid(payload):
            flat = _flatten_item(raw)
            sku = str(flat.get("id") or "")
            if sku and sku not in unique_items:
                unique_items[sku] = flat
        return extract_next_page(payload)

    while True:
        if page_fetcher is not None:
            payload = await page_fetcher(params["url"])
        else:
            try:
                response = await client.get(OZON_ENTRYPOINT, params=params)
            except httpx.HTTPError as exc:
                raise RuntimeError(f"调用 Ozon 接口失败：{type(exc).__name__}") from exc
            if response.status_code in {403, 429}:
                raise RuntimeError(f"Ozon 返回 {response.status_code}，可能触发风控，请降低频率或暂停采集")
            response.raise_for_status()
            payload = _decode_json_response(response)
        next_page = await consume(payload)
        if len(unique_items) >= target or (max_pages is not None and pages >= max_pages):
            break
        if next_page:
            if page_fetcher is not None:
                params = {"url": next_page}
            else:
                params = {"url": next_page} if next_page.startswith(("/", "http://", "https://")) else {"url": params["url"], "page": next_page}
        else:
            current_url = params["url"]
            parsed = urlparse(current_url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query["page"] = str(pages + 1)
            params = {"url": urlunparse(parsed._replace(query=urlencode(query)))}
        await asyncio.sleep(0)
    return pages, unique_items


async def search_one_keyword(
    keyword: str,
    cookies: httpx.Cookies | None,
    target: int = 2000,
    preview: int = 120,
    detail: bool = False,
    client_factory: Callable | None = None,
    page_fetcher: Callable | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """按原关键词及俄语扩展词搜索，合并去重并按相关性排序。"""
    if not keyword or not keyword.strip():
        raise RuntimeError("关键词不能为空")
    terms = expand_keywords(keyword)
    requested_pages = max_pages if max_pages is not None else 100
    if page_fetcher is not None:
        results = [await _search_term(term, None, target, page_fetcher=page_fetcher, max_pages=requested_pages) for term in terms]
    else:
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
            results = [await _search_term(term, cookies, target, client=client, max_pages=requested_pages) for term in terms]
    merged: dict[str, dict[str, Any]] = {}
    for term, (_, items) in zip(terms, results):
        for sku, item in items.items():
            item.setdefault("_matched_terms", []).append(term)
            merged.setdefault(sku, item)
    ordered = sorted(merged.values(), key=lambda item: _item_relevance(item, terms))
    for item in ordered:
        item.pop("_matched_terms", None)
    items = ordered[:max(1, preview)]
    return {
        "keyword": keyword,
        "requested_pages": requested_pages,
        "pages": max((page_count for page_count, _ in results), default=0),
        "unique": len(merged),
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
