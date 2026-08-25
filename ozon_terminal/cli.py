from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from .cookies import CookieVault
from .database import Database
from .exporter import to_csv, to_json

app = typer.Typer(help="Ozon 本地工业数据终端")


def database(path: Path | None) -> Database:
    return Database(path or Path(os.getenv("OZON_TERMINAL_DB", "ozon_terminal.db")))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 9001, reload: bool = False):
    """启动本机 Web 控制台。"""
    import uvicorn
    uvicorn.run("ozon_terminal.api:app", host=host, port=port, reload=reload)


@app.command("cookies-check")
def cookies_check(domain: str = ".ozon.ru"):
    """验证 Chrome Cookie 可读取；值只存在本命令内存。"""
    vault = CookieVault()
    count = vault.import_chrome(domain)
    typer.echo(f"已读取 {count} 个 Cookie（未显示、未落盘）")
    vault.clear()


@app.command("jobs")
def jobs(db: Path | None = typer.Option(None, help="SQLite 文件")):
    store = database(db)
    for job in store.list_jobs():
        typer.echo(f"{job['id']}  {job['status']:<10} pages={job['pages']} items={job['items']}  {job['endpoint']}")
    store.close()


@app.command("export")
def export_job(job_id: str, fmt: str = "json", output: Path | None = None, db: Path | None = None):
    """导出任务数据为 json/csv。"""
    if fmt not in {"json", "csv"}:
        raise typer.BadParameter("fmt 必须是 json 或 csv")
    store = database(db)
    data = to_json(store.records(job_id)) if fmt == "json" else to_csv(store.records(job_id))
    target = output or Path(f"{job_id}.{fmt}")
    target.write_bytes(data)
    store.close()
    typer.echo(str(target.resolve()))


if __name__ == "__main__":
    app()
