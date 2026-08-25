import httpx
import json
import pytest

from ozon_terminal.api import create_app
from ozon_terminal.collector import search_one_keyword


class FakeCookie:
    name = "session"
    value = "REDACTED"
    domain = ".ozon.ru"
    path = "/"


@pytest.mark.asyncio
async def test_search_endpoint_returns_items(tmp_path):
    app = create_app(tmp_path / "search.db")
    async with app.router.lifespan_context(app):
        app.state.cookies.load([FakeCookie()])

        def factory(_cookies):
            requests = [{
                "nextPage": "/search/?page=2",
                "widgetStates": {
                    "tileGridDesktop-test": json.dumps({
                        "items": [{
                            "id": 1, "sku": 1,
                            "mainState": [
                                {"type": "priceV2", "priceV2": {"price": [
                                    {"textStyle": "PRICE", "text": "100"},
                                    {"textStyle": "ORIGINAL_PRICE", "text": "200"}],
                                    "discount": "-50%"}},
                                {"type": "textDS", "textDS": {"text": "示例商品", "id": "name"}},
                                {"type": "labelListV2", "labelListV2": {"items": [
                                    {"type": "text", "text": {"text": "4.8"}},
                                    {"type": "text", "text": {"text": "10"}},
                                ]}},
                            ],
                            "tileImage": {"items": [{"image": {"link": "https://img"}}]},
                            "action": {"link": "/product/test-1/"},
                        }]
                    }),
                },
            }, {"nextPage": None, "widgetStates": {}}]

            call = {"i": 0}

            def handler(request):
                payload = requests[call["i"]]
                call["i"] += 1
                return httpx.Response(200, json=payload)

            return httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=_cookies, headers={"User-Agent": "test"})

        app.state.runner._client_factory = factory
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/search", json={"keyword": "示例", "target": 5, "preview": 10})
        assert response.status_code == 200
        body = response.json()
        assert body["keyword"] == "示例"
        assert body["pages"] == 2
        assert body["unique"] == 1
        assert body["items"][0]["title"] == "示例商品"
        assert body["items"][0]["price"] == "100"
        assert body["items"][0]["rating"] == "4.8"
        assert body["items"][0]["reviews"] == "10"


@pytest.mark.asyncio
async def test_search_endpoint_requires_cookie(tmp_path):
    app = create_app(tmp_path / "search_cookie.db")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/search", json={"keyword": "示例"})
        assert response.status_code == 409