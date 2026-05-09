import time
from collections import defaultdict, deque
from threading import Lock

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import CurrentUser

_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = Lock()


def check_rate_limit(user: CurrentUser, scope: str) -> None:
    limit = max(settings.rate_limit_per_minute, 1)
    window_seconds = 60.0
    now = time.monotonic()
    key = f"{scope}:{user.uid}"

    with _LOCK:
        bucket = _BUCKETS[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise AppError(
                error_code="RATE_LIMITED",
                user_message="Kisa sure icinde cok fazla istek gonderdin. Biraz sonra tekrar dene.",
                developer_message=f"Rate limit exceeded for {key}",
                status_code=429,
                retryable=True,
            )
        bucket.append(now)
