"""In-memory token buckets. Single-process only (we run one uvicorn worker)."""

import threading
import time


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, per_seconds: float) -> bool:
        rate = limit / per_seconds
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(limit), now))
            tokens = min(float(limit), tokens + (now - last) * rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


limiter = RateLimiter()
