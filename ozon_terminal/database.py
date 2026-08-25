from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe SQLite persistence. Cookie values are never accepted or stored."""

    def __init__(self, path: str | Path = "ozon_terminal.db") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    method TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    next_page TEXT,
                    pages INTEGER NOT NULL DEFAULT 0,
                    items INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    page_no INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    UNIQUE(job_id, page_no, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_records_job ON records(job_id, id);
                CREATE TABLE IF NOT EXISTS saved_cookies (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    header TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._conn.execute(
                "UPDATE jobs SET status='paused', error='应用重启后需手动继续' WHERE status IN ('running','pausing','cancelling')"
            )

    def close(self) -> None:
        self._conn.close()

    def create_job(self, endpoint: str, method: str, request: dict[str, Any]) -> dict[str, Any]:
        job_id, now = uuid.uuid4().hex[:12], utcnow()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO jobs(id,endpoint,method,request_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (job_id, endpoint, method.upper(), json.dumps(request, ensure_ascii=False), "pending", now, now),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        data = dict(row)
        data["request"] = json.loads(data.pop("request_json"))
        return data

    def list_jobs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT id FROM jobs ORDER BY created_at DESC").fetchall()
        return [self.get_job(row["id"]) for row in rows]

    def set_status(self, job_id: str, status: str, error: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET status=?,error=?,updated_at=? WHERE id=?",
                (status, error, utcnow(), job_id),
            )

    def save_page(self, job_id: str, page_no: int, items: list[Any], next_page: str | None) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR IGNORE INTO records(job_id,page_no,ordinal,data_json) VALUES(?,?,?,?)",
                [(job_id, page_no, i, json.dumps(item, ensure_ascii=False)) for i, item in enumerate(items)],
            )
            total = self._conn.execute("SELECT COUNT(*) FROM records WHERE job_id=?", (job_id,)).fetchone()[0]
            self._conn.execute(
                "UPDATE jobs SET pages=?,items=?,next_page=?,updated_at=? WHERE id=?",
                (page_no, total, next_page, utcnow(), job_id),
            )

    def records(self, job_id: str) -> list[Any]:
        self.get_job(job_id)
        rows = self._conn.execute("SELECT data_json FROM records WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def upsert_cookie_header(self, header: str, domain: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO saved_cookies(id, header, domain, updated_at) VALUES(1,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET header=excluded.header, domain=excluded.domain, updated_at=excluded.updated_at",
                (header, domain, utcnow()),
            )

    def clear_cookie_header(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM saved_cookies WHERE id=1")

    def fetch_latest_cookie_header(self) -> tuple[str, str] | None:
        row = self._conn.execute("SELECT header, domain FROM saved_cookies WHERE id=1").fetchone()
        if not row:
            return None
        return row[0], row[1]
