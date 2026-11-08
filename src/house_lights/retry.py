"""Bounded retries around a backend call.

This does not replace ``govee-ble-local`` connect, idle-disconnect, or
keep-alive behavior. It only repeats a failed operation a few times.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("house_lights")

# Programmer errors and definitive library refusals will fail the same way again.
_NO_RETRY = frozenset({
    "GoveeBleInvalidValue",
    "GoveeBleNotSupported",
    "GoveeBleAuthError",
    "GoveeCloudAuthError",
    "GoveeCloudError",
})


def retryable(exc: BaseException) -> bool:
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return False
    return type(exc).__name__ not in _NO_RETRY


async def call_with_retry(
    action: Callable[[], Awaitable],
    *,
    attempts: int,
    delay: float,
    label: str,
):
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await action()
        except Exception as exc:
            if not retryable(exc):
                raise
            last = exc
            if attempt == attempts:
                raise
            log.warning("%s failed (%s/%s): %s", label, attempt, attempts, exc)
            if delay > 0:
                await asyncio.sleep(delay)
    assert last is not None
    raise last
