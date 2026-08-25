from __future__ import annotations

import threading
from http.cookiejar import CookieJar
from typing import Iterable

import httpx


class CookieVault:
    """Process-memory-only browser cookie vault."""

    def __init__(self) -> None:
        self._cookies: httpx.Cookies | None = None
        self._count = 0
        self._lock = threading.Lock()

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

    @property
    def ready(self) -> bool:
        return self._cookies is not None

    @property
    def count(self) -> int:
        return self._count
