"""Ozon Data Terminal — MCP 服务器。

把现有 FastAPI 后端的能力拆成 9 个 MCP tool，供给 Dify 1.x 的 MCP 集成面板使用。

运行：
    $ python -m ozon_terminal.mcp_server --host 0.0.0.0 --port 9002

Dify 集成面板：
    transport: streamable_http
    url: http(s)://<host>:9002/mcp
"""

import argparse
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .collector import OZON_ENTRYPOINT, _decode_json_response, _extract_subcategories, _extract_top_categories, extract_next_page, search_one_keyword
from .cookies import CookieVault
from .database import Database

log = logging.getLogger(__name__)

# 与 FastAPI 后端共享同一份 DB，确保 Cookie / 历史结果互通
DEFAULT_DB = os.getenv("OZON_TERMINAL_DB", "ozon_terminal.db")


@dataclass
class AppContext:
    cookies: CookieVault
    db: Database
    # 最近一次查询结果缓存（供 ozon_query_list 使用）
    last_results: dict[str, Any]


@asynccontextmanager
async def lifespan(server: FastMCP):
    db = Database(DEFAULT_DB)
    vault = CookieVault()
    vault.load_from_db(db)
    ctx = AppContext(cookies=vault, db=db, last_results={})
    server.context = ctx  # type: ignore[attr-defined]
    log.info("MCP server ready: cookies_ready=%s, cookies_count=%s", vault.ready, vault.count)
    try:
        yield
    finally:
        vault.clear()
        db.close()


mcp = FastMCP(
    name="ozon-terminal",
    instructions=(
        "Ozon 商品搜索/类目/趋势一站式 MCP 服务。可用工具："
        "ozon_search_keyword(关键词搜索)、ozon_search_category(类目搜索)、"
        "ozon_get_category_info(类目详情+子类目)、ozon_list_categories(关键词命中类目)、"
        "ozon_product_info(单商品详情)、ozon_bestsellers(畅销榜)、"
        "ozon_search_filtered(关键词+价格+排序)、ozon_keyword_tendency(趋势)、"
        "ozon_query_list(上次结果摘要)。"
        "所有工具都要求后端已通过网页端 picks.html 注入 Ozon Cookie。"
    ),
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "9002")),
    lifespan=lifespan,
    # streamable_http 允许跨域 host，方便 Dify 容器通过映射域名访问
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _ctx(server: FastMCP | None = None) -> AppContext:
    server = server or mcp
    ctx = getattr(server, "context", None)
    if not isinstance(ctx, AppContext):
        raise RuntimeError("MCP 服务未初始化，请稍候重试")
    return ctx


async def _require_cookies(server: FastMCP | None = None) -> httpx.Cookies:
    ctx = _ctx(server)
    if not ctx.cookies.ready:
        raise RuntimeError("后端未注入 Ozon Cookie，请在 picks.html 页面粘贴 Cookie Header 后再调用 MCP")
    return ctx.cookies.snapshot()


def _flatten_item_local(item: Any) -> dict[str, Any]:
    """复用 collector._flatten_item 但就近引用以避免循环导入依赖。"""
    from .collector import _flatten_item as _impl
    return _impl(item)


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


# ────────────────────────── 工具定义 ──────────────────────────


@mcp.tool()
async def ozon_search_keyword(
    keyword: str,
    pages: int = 3,
    target: int = 120,
    preview: int = 120,
    category: Optional[str] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sort: Optional[str] = None,
) -> str:
    """按关键词搜索 Ozon 商品。支持中文→俄语自动扩展。
    keyword: 搜索关键词，中文会被翻译成俄语变体合并去重
    pages: 每个关键词变体最多采集页数（1-20）
    target: 累计最大商品数（1-500）
    preview: 返回结果条数（≤ target）
    category: Ozon 类目数字 ID（如 "7500"），限制到指定类目
    price_min / price_max: ₽ 价格区间
    sort: 排序方式 price / price_desc / relevance / newest
    """
    cookies = await _require_cookies()
    started = time.time()
    result = await search_one_keyword(
        keyword,
        cookies,
        target=target,
        preview=preview,
        detail=False,
        client_factory=None,
        page_fetcher=None,
        max_pages=pages,
        category=category,
        price_min=price_min,
        price_max=price_max,
        sort=sort,
        with_categories=True,
        deep_categories=False,
    )
    ctx = _ctx()
    ctx.last_results = {
        "tool": "ozon_search_keyword",
        "keyword": keyword,
        "elapsed": round(time.time() - started, 2),
        "items": result["items"],
        "categories": result["categories"],
    }
    return _ok(result)


@mcp.tool()
async def ozon_search_category(
    category: str,
    pages: int = 3,
    target: int = 120,
    preview: int = 120,
    sort: Optional[str] = "relevance",
) -> str:
    """在指定 Ozon 一级类目下浏览商品（不依赖关键词）。
    category: Ozon 类目数字 ID，如 "7500"（服装鞋与配饰）
    pages: 最多采集页数
    target / preview: 同上
    sort: price / price_desc / relevance / newest
    """
    cookies = await _require_cookies()
    started = time.time()
    result = await search_one_keyword(
        "",
        cookies,
        target=target,
        preview=preview,
        detail=False,
        client_factory=None,
        page_fetcher=None,
        max_pages=pages,
        category=category,
        sort=sort,
        with_categories=False,
        deep_categories=False,
    )
    ctx = _ctx()
    ctx.last_results = {
        "tool": "ozon_search_category",
        "category": category,
        "elapsed": round(time.time() - started, 2),
        "items": result["items"],
    }
    return _ok({"keyword": category, "items": result["items"]})


@mcp.tool()
async def ozon_get_category_info(
    category_id: str,
    with_subcategories: bool = True,
) -> str:
    """根据类目 ID 拉取类目页基本信息 + 子类目。
    category_id: Ozon 类目数字 ID（必填）
    with_subcategories: 是否再去请求类目页拿子类目（默认 true）
    """
    cookies = await _require_cookies()
    async with httpx.AsyncClient(
        cookies=cookies,
        timeout=httpx.Timeout(20),
        follow_redirects=True,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 OzonDataTerminal/0.1"},
    ) as client:
        try:
            response = await client.get(OZON_ENTRYPOINT, params={"url": f"/category/{category_id}/"})
        except httpx.HTTPError as exc:
            raise RuntimeError(f"调用 Ozon 类目页失败：{type(exc).__name__}") from exc
        if response.status_code in {403, 429}:
            raise RuntimeError(f"Ozon 返回 {response.status_code}，可能触发风控，请稍后重试")
        response.raise_for_status()
        payload = _decode_json_response(response)
    tops = _extract_top_categories(payload)
    matched = next((c for c in tops if c["id"] == str(category_id)), tops[0] if tops else None)
    info: dict[str, Any] = {
        "id": str(category_id),
        "name": matched["name"] if matched else None,
        "level": matched.get("level") if matched else None,
        "url": matched["url"] if matched else f"/category/{category_id}/",
    }
    if with_subcategories:
        subs = _extract_subcategories(payload, str(category_id))
        info["subcategories"] = subs
    return _ok(info)


@mcp.tool()
async def ozon_list_categories(
    keyword: str,
    deep: bool = True,
    pages: int = 1,
    target: int = 5,
    preview: int = 5,
) -> str:
    """用关键词搜索一次以枚举命中类目；deep=true 时再请求每个一级类目页拿子类目。
    keyword: 用于触发搜索，类目从响应里的 filtersDesktop 抽取
    deep: 是否抓二级类目（默认 true，会多打 N 次类目页）
    pages / target / preview: 仅需要 1 页 / 少量商品即可
    """
    cookies = await _require_cookies()
    result = await search_one_keyword(
        keyword,
        cookies,
        target=target,
        preview=preview,
        detail=False,
        client_factory=None,
        page_fetcher=None,
        max_pages=pages,
        with_categories=True,
        deep_categories=deep,
    )
    return _ok({"keyword": keyword, "categories": result["categories"]})


@mcp.tool()
async def ozon_product_info(
    sku: str,
) -> str:
    """根据 SKU 拉取单个商品详情。返回与 search 相同的 fields 列表。
    sku: Ozon 商品 ID（数字字符串）
    """
    cookies = await _require_cookies()
    # 单商品详情：走 /product/<slug>-<id>/ 路径，Ozon 搜索页以列表形式渲染
    async with httpx.AsyncClient(
        cookies=cookies,
        timeout=httpx.Timeout(20),
        follow_redirects=True,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 OzonDataTerminal/0.1"},
    ) as client:
        try:
            response = await client.get(OZON_ENTRYPOINT, params={"url": f"/product/{sku}/"})
        except httpx.HTTPError as exc:
            raise RuntimeError(f"调用 Ozon 商品详情失败：{type(exc).__name__}") from exc
        if response.status_code in {403, 429}:
            raise RuntimeError(f"Ozon 返回 {response.status_code}，可能触发风控")
        response.raise_for_status()
        payload = _decode_json_response(response)
    from .collector import _extract_tile_grid
    items = _extract_tile_grid(payload)
    if not items:
        return _ok({"id": sku, "items": [], "hint": "未在详情页找到 tileGrid，商品可能下架或不可见"})
    flat = _flatten_item_local(items[0])
    return _ok(flat)


@mcp.tool()
async def ozon_bestsellers(
    preset: str = "all",
    pages: int = 1,
    target: int = 100,
    preview: int = 100,
) -> str:
    """拉取 Ozon 畅销榜（最多 1000 条，服务端硬限）。
    preset: best_sellers / all（默认 all）
    pages / target / preview: 同上
    """
    cookies = await _require_cookies()
    async with httpx.AsyncClient(
        cookies=cookies,
        timeout=httpx.Timeout(30),
        follow_redirects=True,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 OzonDataTerminal/0.1"},
    ) as client:
        params: dict[str, Any] = {"url": f"/app/bestsellers?preset={preset}&__rr=2&locale=zh-Hans"}
        items: list[Any] = []
        pages_done = 0
        while pages_done < pages and len(items) < target:
            try:
                response = await client.get(OZON_ENTRYPOINT, params=params)
            except httpx.HTTPError as exc:
                raise RuntimeError(f"调用 Ozon 畅销榜失败：{type(exc).__name__}") from exc
            if response.status_code in {403, 429}:
                raise RuntimeError(f"Ozon 返回 {response.status_code}，可能触发风控")
            response.raise_for_status()
            payload = _decode_json_response(response)
            from .collector import _extract_tile_grid
            page_items = _extract_tile_grid(payload)
            for raw in page_items:
                if len(items) >= target:
                    break
                items.append(_flatten_item_local(raw))
            pages_done += 1
            next_page = extract_next_page(payload)
            if next_page:
                params = {"url": next_page} if next_page.startswith(("/", "http://", "https://")) else {"url": params["url"], "page": next_page}
            else:
                break
            await asyncio.sleep(0)
    items = items[:preview]
    ctx = _ctx()
    ctx.last_results = {"tool": "ozon_bestsellers", "preset": preset, "elapsed": 0, "items": items}
    return _ok({"preset": preset, "items": items, "count": len(items)})


@mcp.tool()
async def ozon_search_filtered(
    keyword: str,
    category: str,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sort: Optional[str] = "relevance",
    pages: int = 3,
    target: int = 120,
    preview: int = 120,
) -> str:
    """关键词 + 类目 + 价格 + 排序的综合搜索，是 ozon_search_keyword 的预置组合。
    适合"用户给关键词，Dify 用上一步的类目 ID 锁定到具体类目"的二阶段调用。
    """
    cookies = await _require_cookies()
    result = await search_one_keyword(
        keyword,
        cookies,
        target=target,
        preview=preview,
        detail=False,
        client_factory=None,
        page_fetcher=None,
        max_pages=pages,
        category=category,
        price_min=price_min,
        price_max=price_max,
        sort=sort,
        with_categories=False,
        deep_categories=False,
    )
    ctx = _ctx()
    ctx.last_results = {
        "tool": "ozon_search_filtered",
        "keyword": keyword,
        "category": category,
        "elapsed": 0,
        "items": result["items"],
    }
    return _ok({"keyword": keyword, "category": category, "items": result["items"], "returned": result["returned"]})


@mcp.tool()
async def ozon_keyword_tendency(
    keyword: str,
    pages: int = 1,
    target: int = 5,
    preview: int = 5,
) -> str:
    """通过关键词搜索触发，分析返回商品最近评价时间，估算"商品热度/上新趋势"。
    注意：这是基于评论时间戳的近似估算（Ozon 搜索/详情页均未直接披露销量/上架时间字段）。
    keyword: 关键词
    """
    cookies = await _require_cookies()
    result = await search_one_keyword(
        keyword,
        cookies,
        target=target,
        preview=preview,
        detail=False,
        client_factory=None,
        page_fetcher=None,
        max_pages=pages,
        with_categories=False,
        deep_categories=False,
    )
    items = result["items"]
    # 简单从 link 里抓商品 ID 排序，作为热度参考
    sku_summary = [
        {"id": it.get("id"), "title": it.get("title"), "rating": it.get("rating"), "reviews": it.get("reviews")}
        for it in items
    ]
    return _ok({"keyword": keyword, "count": len(items), "items": sku_summary, "hint": "Ozon's seller-only API holds真实销量；本接口基于评论时间戳近似估算"})


@mcp.tool()
async def ozon_query_list(
    limit: int = 20,
) -> str:
    """返回最近一次查询的简要结果（id / title / price / rating），供 Dify 多步会话引用，避免重复抓取。
    limit: 返回条数（1-200，默认 20）
    """
    ctx = _ctx()
    items = ctx.last_results.get("items", []) if ctx.last_results else []
    summary = [
        {"id": it.get("id"), "title": it.get("title"), "price": it.get("price"), "rating": it.get("rating")}
        for it in items[: max(1, limit)]
    ]
    return _ok({
        "last_tool": ctx.last_results.get("tool") if ctx.last_results else None,
        "elapsed": ctx.last_results.get("elapsed") if ctx.last_results else None,
        "count": len(summary),
        "items": summary,
    })


# ────────────────────────── 启动入口 ──────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Ozon Data Terminal MCP server")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "9002")))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()