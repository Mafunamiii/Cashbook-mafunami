"""Small in-process sign-in limiter for the single-instance deployment."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from collections.abc import Callable


class LoginRateLimiter:
    """Limit failed sign-ins by a non-reversible identity/source fingerprint."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    @staticmethod
    def key(email: str, source_ip: str | None) -> str:
        value = f"{email.casefold().strip()}\x00{source_ip or ''}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def is_limited(self, key: str, maximum: int, window_seconds: int) -> bool:
        attempts = self._prune(key, window_seconds)
        return len(attempts) >= maximum

    def record_failure(self, key: str, window_seconds: int) -> None:
        self._prune(key, window_seconds).append(self._clock())

    def clear(self, key: str) -> None:
        self._attempts.pop(key, None)

    def _prune(self, key: str, window_seconds: int) -> deque[float]:
        attempts = self._attempts[key]
        cutoff = self._clock() - window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        return attempts


login_rate_limiter = LoginRateLimiter()
