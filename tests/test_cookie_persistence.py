import httpx
import pytest

from ozon_terminal.api import create_app
from ozon_terminal.database import Database


HEADER = "session=topsecret; user=alice; token=abc123"


@pytest.mark.asyncio
async def test_cookie_header_persists_and_reloads(tmp_path):
    db_path = tmp_path / "persist.db"

    app1 = create_app(db_path)
    async with app1.router.lifespan_context(app1):
        transport = httpx.ASGITransport(app=app1)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/cookies/header", json={"header": HEADER, "domain": ".ozon.kz"})
            assert r.status_code == 200
            assert r.json() == {"ready": True, "count": 3}
            h = (await client.get("/api/health")).json()
            assert h["cookie_ready"] is True
            assert h["cookie_count"] == 3

    app2 = create_app(db_path)
    async with app2.router.lifespan_context(app2):
        transport = httpx.ASGITransport(app=app2)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            h = (await client.get("/api/health")).json()
            assert h["cookie_ready"] is True, "重启后应自动恢复 Cookie"
            assert h["cookie_count"] == 3

            r = await client.delete("/api/cookies")
            assert r.status_code == 200
            h = (await client.get("/api/health")).json()
            assert h["cookie_ready"] is False

    # 清空后再启动，应回到未连接状态
    app3 = create_app(db_path)
    async with app3.router.lifespan_context(app3):
        transport = httpx.ASGITransport(app=app3)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            h = (await client.get("/api/health")).json()
            assert h["cookie_ready"] is False
