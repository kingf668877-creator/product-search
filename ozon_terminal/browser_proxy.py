from __future__ import annotations

import asyncio
from typing import Any


class BrowserProxy:
    """Coordinates a single pending fetch that the browser performs on behalf of the server."""

    def __init__(self) -> None:
        self._waiters: dict[str, asyncio.Future] = {}

    def announce(self, path: str) -> str:
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._waiters[path] = fut
        return path

    def consume(self, path: str) -> asyncio.Future | None:
        return self._waiters.pop(path, None)

    async def get(self, path: str, timeout: float = 30) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._waiters[path] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._waiters.pop(path, None)