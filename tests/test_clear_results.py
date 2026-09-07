import pytest

from ozon_terminal.api import create_app


class FakeCookie:
    name = "session"
    value = "REDACTED"
    domain = ".ozon.ru"
    path = "/"


@pytest.mark.asyncio
async def test_clear_results_endpoint(tmp_path):
    app = create_app(tmp_path / "clear.db")
    async with app.router.lifespan_context(app):
        # 预填一些记录
        db = app.state.db
        job = db.create_job("https://www.ozon.ru/api/test", "POST", {"k": "v"})
        db.save_page(job["id"], 1, [{"id": 1, "title": "x"}], None)

        # cookie 也得 ready 否则 /api/search 会 409，但 clear-results 不依赖
        app.state.cookies.load([FakeCookie()])

        transport = __import__("httpx").ASGITransport(app=app)
        import httpx as _h
        async with _h.AsyncClient(transport=transport, base_url="http://test") as client:
            # 删 records + jobs
            response = await client.delete("/api/admin/clear-results")
            assert response.status_code == 200
            body = response.json()
            assert body["cookies_kept"] is True
            assert body["deleted_records"] == 1
            # 再次查 jobs/records，确认清空
            assert db._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
            assert db._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
            # Cookie 没动
            assert app.state.cookies.ready is True
            assert app.state.cookies.count == 1


@pytest.mark.asyncio
async def test_clear_results_keeps_cookies_intact(tmp_path):
    app = create_app(tmp_path / "clear2.db")
    async with app.router.lifespan_context(app):
        db = app.state.db
        # 写入一条 cookie header
        app.state.cookies.load_from_header("a=1; b=2", ".ozon.kz")
        app.state.cookies.save_to_db(db)
        assert db._conn.execute("SELECT COUNT(*) FROM saved_cookies").fetchone()[0] == 1

        transport = __import__("httpx").ASGITransport(app=app)
        import httpx as _h
        async with _h.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete("/api/admin/clear-results")
            assert response.status_code == 200
            assert db._conn.execute("SELECT COUNT(*) FROM saved_cookies").fetchone()[0] == 1