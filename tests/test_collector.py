import httpx
import pytest

from ozon_terminal.collector import JobRunner, extract_items, extract_next_page
from ozon_terminal.cookies import CookieVault
from ozon_terminal.database import Database


class FakeCookie:
    name = "session"
    value = "TOP-SECRET-COOKIE"
    domain = ".ozon.ru"
    path = "/"


@pytest.fixture
def setup(tmp_path):
    db = Database(tmp_path / "test.db")
    vault = CookieVault()
    vault.load([FakeCookie()])
    yield db, vault
    db.close()


@pytest.mark.asyncio
async def test_nextpage_is_collected_sequentially(setup):
    db, vault = setup
    seen = []

    def handler(request):
        seen.append(str(request.url))
        page = request.url.params.get("page")
        payload = {"items": [{"id": len(seen)}], "nextPage": "p2" if page is None else None}
        return httpx.Response(200, json=payload)

    def factory(cookies):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=cookies)

    job = db.create_job("https://www.ozon.ru/api/list", "GET", {"q": "bolt"})
    runner = JobRunner(db, vault, factory)
    await runner.start(job["id"])
    await runner.wait(job["id"])
    result = db.get_job(job["id"])
    assert result["status"] == "completed"
    assert result["pages"] == 2
    assert db.records(job["id"]) == [{"id": 1}, {"id": 2}]
    assert "page=p2" in seen[1]


@pytest.mark.asyncio
async def test_pause_then_resume_from_checkpoint(setup):
    db, vault = setup
    seen = []
    runner = None

    def handler(request):
        nonlocal runner
        token = request.url.params.get("page")
        seen.append(token)
        if len(seen) == 1:
            runner.request_pause(job["id"])
        return httpx.Response(200, json={"items": [{"token": token}], "nextPage": "B" if token is None else None})

    def factory(cookies):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=cookies)

    job = db.create_job("https://api.ozon.ru/v1/list", "GET", {})
    runner = JobRunner(db, vault, factory)
    await runner.start(job["id"])
    await runner.wait(job["id"])
    assert db.get_job(job["id"])["status"] == "paused"
    assert db.get_job(job["id"])["next_page"] == "B"
    await runner.resume(job["id"])
    await runner.wait(job["id"])
    assert seen == [None, "B"]
    assert db.get_job(job["id"])["status"] == "completed"


def test_payload_extractors():
    payload = {"data": {"products": [{"sku": 1}], "pagination": {"next_page": "x"}}}
    assert extract_items(payload) == [{"sku": 1}]
    assert extract_next_page(payload) == "x"
