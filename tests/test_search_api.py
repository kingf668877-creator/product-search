import httpx
import json
import pytest

from ozon_terminal.api import create_app
from ozon_terminal.collector import (
    OZON_ENTRYPOINT,
    _decode_json_response,
    _repair_mojibake,
    _search_term,
    expand_keywords,
    next_request,
    search_one_keyword,
)


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
                                        {"priceV2": {"price": [
                                            {"textStyle": "PRICE", "text": "100"},
                                            {"textStyle": "ORIGINAL_PRICE", "text": "200"}],
                                            "discount": "-50%"}},
                                        {"textDS": {"text": "示例商品"}, "id": "name"},
                                        {"labelListV2": {"items": [
                                            {"text": {"text": "4.8"}},
                                            {"text": {"text": "10"}},
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
            response = await client.post("/api/search", json={"keyword": "示例", "target": 5, "preview": 10, "pages": 2})
        assert response.status_code == 200
        body = response.json()
        assert body["keyword"] == "示例"
        assert body["requested_pages"] == 2
        assert body["pages"] == 2
        assert body["unique"] == 1
        assert body["items"][0]["title"] == "示例商品"
        assert body["items"][0]["price"] == "100"
        assert body["items"][0]["rating"] == "4.8"
        assert body["items"][0]["reviews"] == "10"


@pytest.mark.asyncio
async def test_search_endpoint_respects_page_limit(tmp_path):
    app = create_app(tmp_path / "search_pages.db")
    async with app.router.lifespan_context(app):
        app.state.cookies.load([FakeCookie()])
        calls = {"count": 0}

        def factory(_cookies):
            def handler(request):
                calls["count"] += 1
                return httpx.Response(200, json={"nextPage": "/search/?page=2", "widgetStates": {}})

            return httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=_cookies)

        app.state.runner._client_factory = factory
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/search", json={"keyword": "示例", "target": 2000, "preview": 10, "pages": 1})
        assert response.status_code == 200
        assert response.json()["requested_pages"] == 1
        assert response.json()["pages"] == 1
        assert calls["count"] == 1

def test_keyword_expansion_pagination_forms_and_mojibake_repair():
    assert expand_keywords("男士外套") == [
        "男士外套",
        "мужскойкуртка",
        "мужскойпальто",
        "мужскойверхняя одежда",
        "мужчинакуртка",
        "мужчинапальто",
        "мужчинаверхняя одежда",
    ]
    endpoint = "https://www.ozon.kz/api/entrypoint-api.bx/page/json/v2"
    assert next_request(endpoint, "GET", {"url": "/search/"}, "/search/?page=2")[0] == "https://www.ozon.kz/search/?page=2"
    assert next_request(endpoint, "GET", {"url": "/search/"}, "https://www.ozon.kz/search/?page=2")[0] == "https://www.ozon.kz/search/?page=2"
    url, request = next_request(endpoint, "GET", {"url": "/search/"}, "token-2")
    assert url == endpoint
    assert request["page"] == "token-2"
    mojibake = "мужской".encode("utf-8").decode("latin-1")
    response = httpx.Response(200, content=json.dumps({"title": mojibake}, ensure_ascii=False).encode("utf-8"))
    assert _decode_json_response(response)["title"] == "мужской"

    twice_encoded = "大好"
    for _ in range(2):
        twice_encoded = twice_encoded.encode("utf-8").decode("latin-1")
    assert twice_encoded == "Ã¥Â¤Â§Ã¥Â¥Â½"
    assert _repair_mojibake(twice_encoded) == "大好"


@pytest.mark.asyncio
async def test_search_adds_sequential_page_when_next_page_is_missing():
    seen_urls = []

    async def fetcher(url):
        seen_urls.append(url)
        return {"widgetStates": {}}

    pages, items = await _search_term("示例", None, target=100, page_fetcher=fetcher, max_pages=3)

    assert pages == 3
    assert items == {}
    assert "page=" not in seen_urls[0]
    assert "page=2" in seen_urls[1]
    assert "page=3" in seen_urls[2]


@pytest.mark.asyncio
async def test_expanded_search_uses_endpoint_and_maximum_actual_pages():
    seen_urls = []
    calls = {"男士": 0, "мужской": 0, "мужчина": 0}

    def tile(sku, title):
        return {"widgetStates": {"tileGridDesktop-test": json.dumps({"items": [{
            "id": sku,
            "mainState": [{"textDS": {"text": title}, "id": "name"}],
        }]})}}

    def factory(_cookies):
        def handler(request):
            seen_urls.append(str(request.url).split("?")[0])
            text = request.url.params["url"].split("text=")[-1].split("&")[0]
            term = httpx.URL(f"https://test/?text={text}").params["text"]
            calls[term] += 1
            if term == "мужской" and calls[term] == 1:
                return httpx.Response(200, json={**tile(1, "мужской куртка"), "nextPage": "token-2"})
            return httpx.Response(200, json={**tile(calls[term] + (0 if term == "мужской" else 10), term), "nextPage": None})
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=_cookies)

    result = await search_one_keyword("男士", httpx.Cookies(), preview=10, client_factory=factory, max_pages=2)
    assert result["keyword"] == "男士"
    assert result["requested_pages"] == 2
    assert result["pages"] == 2
    assert result["unique"] == 4
    assert all(url == OZON_ENTRYPOINT for url in seen_urls)
    assert result["items"][0]["title"] == "男士"


@pytest.mark.asyncio
async def test_search_endpoint_requires_cookie(tmp_path):
    app = create_app(tmp_path / "search_cookie.db")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/search", json={"keyword": "示例"})
        assert response.status_code == 409