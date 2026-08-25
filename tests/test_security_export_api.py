import json
from pathlib import Path

import httpx
import pytest

from ozon_terminal.api import create_app
from ozon_terminal.cookies import CookieVault
from ozon_terminal.database import Database
from ozon_terminal.exporter import to_csv, to_json


class FakeCookie:
    name = "secure_session"
    value = "NEVER-WRITE-THIS-SECRET"
    domain = ".ozon.ru"
    path = "/"


def test_cookie_is_memory_only(tmp_path):
    db_path = tmp_path / "security.db"
    db = Database(db_path)
    vault = CookieVault()
    vault.load([FakeCookie()])
    job = db.create_job("https://www.ozon.ru/api", "GET", {"query": "safe"})
    db.close()
    assert FakeCookie.value.encode() not in db_path.read_bytes()
    assert "secure_session" not in json.dumps(job)


def test_exports_flatten_records():
    records = [{"id": 1, "meta": {"name": "螺栓"}, "tags": ["M8"]}]
    assert "螺栓" in to_json(records).decode()
    csv_text = to_csv(records).decode("utf-8-sig")
    assert "meta.name" in csv_text and "螺栓" in csv_text


@pytest.mark.asyncio
async def test_api_requires_cookie_and_rejects_non_ozon(tmp_path):
    app = create_app(tmp_path / "api.db")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            bad = await client.post("/api/jobs", json={"endpoint": "https://example.com/api", "method": "GET"})
            assert bad.status_code == 422
            guarded = await client.post("/api/jobs", json={"endpoint": "https://www.ozon.ru/api", "method": "GET"})
            assert guarded.status_code == 409
            health = await client.get("/api/health")
            assert health.json() == {"ok": True, "cookie_ready": False, "cookie_count": 0}
