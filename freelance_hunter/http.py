"""Cliente HTTP educado: intervalo mínimo por domínio, jitter e backoff em 429/5xx."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


class PoliteClient:
    def __init__(self, min_interval: float = 8.0, max_retries: int = 3, timeout: float = 30.0):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
        )

    async def _wait_turn(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last.get(host, 0) + self.min_interval + random.uniform(0, 3) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def get(self, url: str, **kwargs) -> httpx.Response:
        host = urlparse(url).netloc
        for attempt in range(self.max_retries + 1):
            await self._wait_turn(host)
            try:
                resp = await self._client.get(url, **kwargs)
            except httpx.TransportError as e:
                if attempt == self.max_retries:
                    raise
                log.warning("Falha de rede em %s (%s); tentando de novo", host, e)
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt == self.max_retries:
                        resp.raise_for_status()
                    retry_after = resp.headers.get("Retry-After", "")
                    delay = float(retry_after) if retry_after.isdigit() else 30 * 2**attempt
                    log.warning("%s respondeu %s; aguardando %.0fs", host, resp.status_code, delay)
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp
            await asyncio.sleep(10 * 2**attempt)
        raise RuntimeError("inalcançável")

    async def aclose(self) -> None:
        await self._client.aclose()
