"""Redis-based rate limiting."""
from datetime import datetime
from typing import Optional, Tuple

import redis

from config import settings


class RateLimiter:
    """Rate limiter using Redis sliding window algorithm."""

    def __init__(
        self,
        max_requests: int = 5,
        window_seconds: int = 3600,
    ):
        """
        Initialize the rate limiter.

        Args:
            max_requests: Maximum requests allowed per window (default: 5)
            window_seconds: Time window in seconds (default: 3600 = 1 hour)
        """
        self.redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True
        )
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def _get_key(self, identifier: str) -> str:
        """Generate Redis key for rate limit tracking."""
        return f"rate_limit:{identifier}"

    def is_allowed(self, identifier: str) -> Tuple[bool, Optional[int]]:
        """
        Check if a request is allowed under the rate limit.

        Uses a sliding window algorithm with Redis sorted sets.
        Each request timestamp is stored as a score, and old entries
        are pruned on each check.

        Args:
            identifier: Unique identifier (e.g., IP address)

        Returns:
            Tuple of (is_allowed, retry_after_seconds)
            - is_allowed: True if request is within rate limit
            - retry_after_seconds: Seconds until rate limit resets (None if allowed)
        """
        key = self._get_key(identifier)
        now = datetime.utcnow().timestamp()
        window_start = now - self.window_seconds

        pipe = self.redis_client.pipeline()

        # Remove entries outside the current window
        pipe.zremrangebyscore(key, 0, window_start)

        # Count requests in current window
        pipe.zcard(key)

        # Add current request timestamp
        pipe.zadd(key, {str(now): now})

        # Set key expiration
        pipe.expire(key, self.window_seconds)

        results = pipe.execute()
        request_count = results[1]

        if request_count >= self.max_requests:
            # Get oldest entry to calculate retry time
            oldest = self.redis_client.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_timestamp = oldest[0][1]
                retry_after = int(oldest_timestamp + self.window_seconds - now) + 1
                return (False, max(retry_after, 1))
            return (False, self.window_seconds)

        return (True, None)

    def get_remaining(self, identifier: str) -> int:
        """
        Get remaining requests allowed in current window.

        Args:
            identifier: Unique identifier

        Returns:
            Number of remaining requests allowed
        """
        key = self._get_key(identifier)
        now = datetime.utcnow().timestamp()
        window_start = now - self.window_seconds

        # Clean old entries and count current
        self.redis_client.zremrangebyscore(key, 0, window_start)
        current_count = self.redis_client.zcard(key)

        return max(0, self.max_requests - current_count)


# Global rate limiter instance
rate_limiter = RateLimiter()
