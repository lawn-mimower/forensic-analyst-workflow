"""
Per-provider rate limiter with token-bucket style enforcement.

Extracted from lightrag_init.py for reuse across providers.
"""

import asyncio
import time as _time


class RateLimiter:
    """Enforces a minimum delay between API calls across all concurrent workers."""

    def __init__(self, requests_per_minute: int = 30):
        self._delay = 60.0 / requests_per_minute
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self):
        async with self._lock:
            now = _time.monotonic()
            wait_time = self._delay - (now - self._last_call)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_call = _time.monotonic()


# ---------------------------------------------------------------------------
# Per-provider registry: one RateLimiter instance per provider name
# ---------------------------------------------------------------------------
_provider_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(provider: str = "default", rpm: int = 30) -> RateLimiter:
    """Return a RateLimiter for the given provider (created on first call)."""
    if provider not in _provider_limiters:
        _provider_limiters[provider] = RateLimiter(requests_per_minute=rpm)
    return _provider_limiters[provider]
