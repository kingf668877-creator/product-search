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

    pages, items, categories = await _search_term("示例", None, target=100, page_fetcher=fetcher, max_pages=3)

    assert pages == 3
    assert items == {}
    assert categories == []
    assert "page=" not in seen_urls[0]
    assert "page=2" in seen_urls[1]
    assert "page=3" in seen_urls[2]


@pytest.mark.asyncio
async def test_search_extracts_top_categories_from_filters_widget():
    filters_widget = json.dumps({
            "sections": [
                {"filters": [{
                    "type": "categoryFilter",
                    "categoryFilter": {
                        "title": "Категория",
                        "categories": [
                            {"title": "Одежда", "level": 0, "urlValue": "/category/odezhda-obuv-i-aksessuary-7500/?__rr=1&deny_category_prediction=true&from_global=true&text=dress", "testInfo": {"automatizationId": "filter-category-item-7500"}},
                            {"title": "Ароматы для дома", "level": 0, "urlValue": "/category/aromaty-dlya-doma-30931/", "testInfo": {"automatizationId": "filter-category-item-30931"}},
                        ],
                    },
                }]}
            ]
        })

    async def fetcher(_url):
        return {"widgetStates": {"filtersDesktop-1": filters_widget, "tileGridDesktop-1": json.dumps({"items": []})}}

    pages, items, categories = await _search_term("dress", None, target=10, page_fetcher=fetcher, max_pages=1)
    assert pages == 1
    assert items == {}
    assert categories == [
        {"id": "7500", "name": "Одежда", "level": 0, "url": "/category/odezhda-obuv-i-aksessuary-7500/?__rr=1&deny_category_prediction=true&from_global=true&text=dress"},
        {"id": "30931", "name": "Ароматы для дома", "level": 0, "url": "/category/aromaty-dlya-doma-30931/"},
    ]


@pytest.mark.asyncio
async def test_search_fetches_subcategories_when_deep_categories_enabled():
    filters_widget = json.dumps({
        "sections": [{"filters": [{
            "type": "categoryFilter",
            "categoryFilter": {
                "title": "Категория",
                "categories": [
                    {"title": "Одежда", "level": 0, "urlValue": "/category/odezhda-obuv-i-aksessuary-7500/", "testInfo": {"automatizationId": "filter-category-item-7500"}},
                ],
            },
        }]}]
    })
    sub_menu = json.dumps({
        "items": [
            {"title": "Женская одежда", "url": "/category/zhenskaya-odezhda-7501/"},
            {"title": "Мужская одежда", "url": "/category/muzhskaya-odezhda-7502/"},
        ]
    })

    class _FakeResp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.content = json.dumps(payload).encode("utf-8")
            self.headers = {"content-type": "application/json"}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=None, response=httpx.Response(self.status_code))

    class _FakeAsyncClient:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, _url, params=None):
            url = params.get("url", "") if params else ""
            self.calls.append(url)
            if url.startswith("/search/"):
                return _FakeResp(200, {"widgetStates": {
                    "filtersDesktop-1": filters_widget,
                    "tileGridDesktop-1": json.dumps({"items": []}),
                }})
            if url.startswith("/category/"):
                return _FakeResp(200, {"widgetStates": {
                    "horizontalCategoryMenu-1-default-1": sub_menu,
                }})
            return _FakeResp(404, {})

    client = _FakeAsyncClient()

    async def _run():
        async with client:
            return await _search_term(
                "dress",
                None,
                target=10,
                client=client,
                max_pages=1,
                deep_categories=True,
            )

    pages, items, categories = await _run()

    assert pages == 1
    assert items == {}
    assert len(categories) == 1
    assert categories[0]["id"] == "7500"
    assert categories[0]["subcategories"] == [
        {"id": "7501", "name": "Женская одежда", "level": 1, "url": "/category/zhenskaya-odezhda-7501/", "parent_id": "7500"},
        {"id": "7502", "name": "Мужская одежда", "level": 1, "url": "/category/muzhskaya-odezhda-7502/", "parent_id": "7500"},
    ]


@pytest.mark.asyncio
async def test_search_deep_categories_off_by_default():
    """默认 deep_categories=False 时不应请求类目页。"""
    filters_widget = json.dumps({
        "sections": [{"filters": [{
            "type": "categoryFilter",
            "categoryFilter": {
                "title": "Категория",
                "categories": [
                    {"title": "Одежда", "level": 0, "urlValue": "/category/odezhda-7500/", "testInfo": {"automatizationId": "filter-category-item-7500"}},
                ],
            },
        }]}]
    })

    class _FakeResp:
        def __init__(self, payload):
            self.status_code = 200
            self.content = json.dumps(payload).encode("utf-8")
            self.headers = {"content-type": "application/json"}

        def raise_for_status(self):
            pass

    class _FakeAsyncClient:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, _url, params=None):
            url = params.get("url", "") if params else ""
            self.calls.append(url)
            return _FakeResp({"widgetStates": {
                "filtersDesktop-1": filters_widget,
                "tileGridDesktop-1": json.dumps({"items": []}),
            }})

    client = _FakeAsyncClient()

    async def _run():
        async with client:
            return await _search_term("dress", None, target=10, client=client, max_pages=1)

    pages, items, categories = await _run()

    assert all(not call.startswith("/category/") for call in client.calls)
    assert "subcategories" not in categories[0]


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