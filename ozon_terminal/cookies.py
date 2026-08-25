from __future__ import annotations

import sqlite3
import threading
from http.cookiejar import CookieJar
from typing import Iterable, Optional

import httpx


class CookieVault:
    """Process-memory cookie vault with optional SQLite persistence."""

    def __init__(self) -> None:
        self._cookies: httpx.Cookies | None = None
        self._count = 0
        self._lock = threading.Lock()
        self._source_header: str | None = None  # 用于持久化
        self._source_domain: str | None = None

    def import_chrome(self, domain: str = ".ozon.ru") -> int:
        try:
            import browser_cookie3
            jar: CookieJar = browser_cookie3.chrome(domain_name=domain)
        except Exception as exc:
            raise RuntimeError("无法读取 Chrome Cookie；请关闭 Chrome 后重试，或检查系统密钥权限") from exc
        return self.load(jar)

    def load(self, cookies: Iterable) -> int:
        vault = httpx.Cookies()
        count = 0
        for cookie in cookies:
            vault.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path or "/")
            count += 1
        if not count:
            raise RuntimeError("Chrome 中未找到匹配的 Ozon Cookie")
        with self._lock:
            self._cookies, self._count = vault, count
            self._source_header = None
            self._source_domain = None
        return count

    def load_from_browser(self, raw: Iterable[dict], default_domain: str = ".ozon.kz") -> int:
        vault = httpx.Cookies()
        count = 0
        for item in raw:
            name = item.get("name")
            value = item.get("value")
            if not name or value is None:
                continue
            domain = (item.get("domain") or default_domain).lstrip(".")
            if not domain:
                domain = default_domain.lstrip(".")
            path = item.get("path") or "/"
            vault.set(name, str(value), domain="." + domain, path=path)
            count += 1
        if not count:
            raise ValueError("浏览器未提供任何 Cookie")
        with self._lock:
            self._cookies, self._count = vault, count
            self._source_header = None
            self._source_domain = default_domain
        return count

    def load_from_header(self, header_value: str, domain: str = ".ozon.kz") -> int:
        """Accept raw Cookie request header text (e.g. copy from DevTools)."""
        if header_value.startswith("base64:"):
            import base64
            header_value = base64.b64decode(header_value[len("base64:"):]).decode("utf-8", "replace")
        vault = httpx.Cookies()
        count = 0
        for chunk in header_value.split(";"):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            name, _, value = chunk.partition("=")
            name = name.strip()
            value = value.strip()
            if not name:
                continue
            vault.set(name, value, domain="." + domain.lstrip("."), path="/")
            count += 1
        if not count:
            raise ValueError("Cookie 字符串为空或格式错误")
        with self._lock:
            self._cookies, self._count = vault, count
            self._source_header = header_value
            self._source_domain = domain
        return count

    def load_from_db(self, db) -> int:
        """从数据库恢复最近一次上传的 Cookie Header。"""
        try:
            row = db.fetch_latest_cookie_header()
        except Exception:
            return 0
        if not row:
            return 0
        header_value, domain = row
        try:
            return self.load_from_header(header_value, domain)
        except ValueError:
            return 0

    def save_to_db(self, db) -> int:
        """把当前 Cookie 落盘，方便下次自动加载。"""
        with self._lock:
            header = self._source_header
            domain = self._source_domain or ".ozon.kz"
            count = self._count
        if not header:
            return 0
        db.upsert_cookie_header(header, domain)
        return count

    def snapshot(self) -> httpx.Cookies:
        with self._lock:
            if self._cookies is None:
                raise RuntimeError("尚未导入 Chrome Cookie")
            copied = httpx.Cookies()
            for cookie in self._cookies.jar:
                copied.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path or "/")
            return copied

    def clear(self) -> None:
        with self._lock:
            self._cookies, self._count = None, 0
            self._source_header = None
            self._source_domain = None

    @property
    def ready(self) -> bool:
        return self._cookies is not None

    @property
    def count(self) -> int:
        return self._count
