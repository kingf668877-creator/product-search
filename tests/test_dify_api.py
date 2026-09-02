import json
import os
from urllib.parse import unquote, parse_qsl, urlsplit

import httpx
import pytest

from ozon_terminal.api import create_app


class FakeCookie:
    name = "session"
    value = "REDACTED"
    domain = ".ozon.ru"
    path = "/"


def _build_app(tmp_path, monkeypatch=None, key="dify-secret"):
    if monkeypatch is not None:
        monkeypatch.setenv("OZON_DIFY_API_KEY", key)
    elif "OZON_DIFY_API_KEY" not in os.environ:
        os.environ["OZON_DIFY_API_KEY"] = key
    app = create_app(tmp_path / "dify.db")
    return app


def _mount_factory(app, request):
    def factory(_cookies):
        def handler(_request):
            return httpx.Response(
                200,
                json={
                    "nextPage": None,
                    "widgetStates": {
                        "tileGridDesktop-test": json.dumps({
                            "items": [{
                                "id": 1,
                                "mainState": [
                                    {"type": "priceV2", "priceV2": {"price": [{"textStyle": "PRICE", "text": "100"}]}},
                                    {"type": "textDS", "textDS": {"text": "示例"}, "id": "name"},
                                ],
                                "tileImage": {"items": [{"image": {"link": "https://img"}}]},
                                "action": {"link": "/product/test-1/"},
                            }],
                        }),
                    },
                },
            )

        return httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=_cookies)

    app.state.runner._client_factory = factory
    return app


@pytest.mark.asyncio
async def test_dify_search_requires_bearer(monkeypatch, tmp_path):
    _build_app(tmp_path, monkeypatch=monkeypatch, key="dify-secret")
    app = _mount_factory(_build_app(tmp_path, monkeypatch=monkeypatch, key="dify-secret"), request=None)
    async with app.router.lifespan_context(app):
        app.state.cookies.load([FakeCookie()])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/dify/search", json={"keywords": ["外套"]})
            assert response.status_code == 401
            response = await client.post(
                "/api/dify/search",
                json={"keywords": ["外套"]},
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert response.status_code == 401


@pytest.mark.asyncio
async def test_dify_search_serializes_keywords(monkeypatch, tmp_path):
    monkeypatch.setenv("OZON_DIFY_API_KEY", "dify-secret")
    app = create_app(tmp_path / "dify_serial.db")
    app.state.cookies.load([FakeCookie()])

    seen = {"order": []}

    def factory(_cookies):
        def handler(_request):
            term = unquote(_request.url.params["url"].split("text=")[-1].split("&")[0])
            seen["order"].append(term)
            return httpx.Response(
                200,
                json={
                    "nextPage": None,
                    "widgetStates": {
                        "tileGridDesktop-test": json.dumps({
                            "items": [{
                                "id": len(seen["order"]),
                                "mainState": [{"textDS": {"text": term}, "id": "name"}],
                            }],
                        }),
                    },
                },
            )

        return httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=_cookies)

    app.state.runner._client_factory = factory

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/dify/search",
                json={"keywords": ["外套", "男士外套", "外套", "  "], "pages": 1, "target": 5, "preview": 5},
                headers={"Authorization": "Bearer dify-secret"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["count"] == 2
            assert [r["keyword"] for r in body["results"]] == ["外套", "男士外套"]
            # 外套先匹配：外套 → куртка → пальто → верхняя одежда
            assert seen["order"][:3] == ["外套", "куртка", "пальто"]


@pytest.mark.asyncio
async def test_dify_search_param_bounds(monkeypatch, tmp_path):
    monkeypatch.setenv("OZON_DIFY_API_KEY", "dify-secret")
    app = create_app(tmp_path / "dify_bounds.db")
    app.state.cookies.load([FakeCookie()])
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": "Bearer dify-secret"}
            response = await client.post("/api/dify/search", json={"keywords": []}, headers=headers)
            assert response.status_code == 422
            response = await client.post(
                "/api/dify/search",
                json={"keywords": ["a"], "pages": 0},
                headers=headers,
            )
            assert response.status_code == 422
            response = await client.post(
                "/api/dify/search",
                json={"keywords": ["a"], "pages": 50},
                headers=headers,
            )
            assert response.status_code == 422


@pytest.mark.asyncio
async def test_dify_search_requires_cookie(monkeypatch, tmp_path):
    monkeypatch.setenv("OZON_DIFY_API_KEY", "dify-secret")
    app = create_app(tmp_path / "dify_cookie.db")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/dify/search",
                json={"keywords": ["外套"]},
                headers={"Authorization": "Bearer dify-secret"},
            )
            assert response.status_code == 409


@pytest.mark.asyncio
async def test_dify_openapi_excludes_admin(monkeypatch, tmp_path):
    monkeypatch.setenv("OZON_DIFY_API_KEY", "dify-secret")
    app = create_app(tmp_path / "dify_openapi.db")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/openapi/dify.json",
                headers={"Authorization": "Bearer dify-secret"},
            )
            assert response.status_code == 200
            spec = response.json()
            paths = list(spec["paths"].keys())
            assert paths == ["/api/dify/search"]
            operation = spec["paths"]["/api/dify/search"]["post"]
            assert operation["security"] == [{"BearerAuth": []}]
            assert spec["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"


@pytest.mark.asyncio
async def test_dify_search_forwards_filters(monkeypatch, tmp_path):
    monkeypatch.setenv("OZON_DIFY_API_KEY", "dify-secret")
    app = create_app(tmp_path / "dify_filters.db")
    app.state.cookies.load([FakeCookie()])

    seen_urls = []

    def factory(_cookies):
        def handler(request):
            seen_urls.append(str(request.url))
            return httpx.Response(200, json={"nextPage": None, "widgetStates": {}})

        return httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=_cookies)

    app.state.runner._client_factory = factory

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/dify/search",
                json={
                    "keywords": ["dress"],
                    "pages": 1,
                    "category": "7500",
                    "price_min": 1000,
                    "price_max": 3000,
                    "sort": "price",
                },
                headers={"Authorization": "Bearer dify-secret"},
            )
            assert response.status_code == 200
            first_url = seen_urls[0]
            parsed = parse_qsl(urlsplit(unquote(first_url)).query, keep_blank_values=True)
            params = {k: v for k, v in parsed}
            assert params.get("category") == "7500"
            assert params.get("minPrice") == "1000"
            assert params.get("maxPrice") == "3000"
            assert params.get("sort") == "price"
            assert params.get("text") == "dress"


@pytest.mark.asyncio
async def test_dify_search_rejects_invalid_price_range(monkeypatch, tmp_path):
    monkeypatch.setenv("OZON_DIFY_API_KEY", "dify-secret")
    app = create_app(tmp_path / "dify_price.db")
    app.state.cookies.load([FakeCookie()])
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": "Bearer dify-secret"}
            response = await client.post(
                "/api/dify/search",
                json={"keywords": ["dress"], "price_min": 3000, "price_max": 1000},
                headers=headers,
            )
            assert response.status_code == 422


@pytest.mark.asyncio
async def test_dify_openapi_requires_bearer(monkeypatch, tmp_path):
    monkeypatch.delenv("OZON_DIFY_API_KEY", raising=False)
    app = create_app(tmp_path / "dify_openapi_no_key.db")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/openapi/dify.json")
            assert response.status_code == 401


@pytest.mark.asyncio
async def test_dify_search_accepts_deep_categories_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("OZON_DIFY_API_KEY", "dify-secret")
    app = create_app(tmp_path / "dify_deep.db")
    app.state.cookies.load([FakeCookie()])

    sub_menu = json.dumps({
        "items": [
            {"title": "Женская одежда", "url": "/category/zhenskaya-odezhda-7501/"},
        ]
    })

    seen_urls = []

    def factory(_cookies):
        def handler(request):
            url = request.url.params["url"]
            seen_urls.append(url)
            if url.startswith("/category/"):
                return httpx.Response(200, json={"widgetStates": {
                    "horizontalCategoryMenu-1-default-1": sub_menu,
                }})
            return httpx.Response(200, json={"nextPage": None, "widgetStates": {
                "filtersDesktop-1": json.dumps({
                    "sections": [{"filters": [{
                        "type": "categoryFilter",
                        "categoryFilter": {"categories": [
                            {"title": "Одежда", "level": 0, "urlValue": "/category/odezhda-7500/", "testInfo": {"automatizationId": "filter-category-item-7500"}},
                        ]},
                    }]}]
                }),
            }})

        return httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=_cookies)

    app.state.runner._client_factory = factory

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/dify/search",
                json={"keywords": ["dress"], "pages": 1, "target": 5, "preview": 5, "deep_categories": True},
                headers={"Authorization": "Bearer dify-secret"},
            )
            assert response.status_code == 200
            body = response.json()
            assert any("/category/" in url for url in seen_urls)
            assert body["results"][0]["categories"][0]["subcategories"][0]["id"] == "7501"