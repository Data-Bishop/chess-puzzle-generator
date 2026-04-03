"""Tests for the Redis sliding-window rate limiter."""
import time
import pytest
import fakeredis

from rate_limiter import RateLimiter


@pytest.fixture()
def limiter(monkeypatch):
    """RateLimiter wired to an in-memory fake Redis (5 req / 3600 s)."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("rate_limiter.redis.from_url", lambda *a, **kw: fake)
    rl = RateLimiter(max_requests=5, window_seconds=3600)
    return rl


@pytest.fixture()
def tight_limiter(monkeypatch):
    """RateLimiter with a very short window to test retry-after logic."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("rate_limiter.redis.from_url", lambda *a, **kw: fake)
    rl = RateLimiter(max_requests=2, window_seconds=10)
    return rl


class TestIsAllowed:
    def test_first_request_allowed(self, limiter):
        allowed, retry_after = limiter.is_allowed("192.168.1.1")
        assert allowed is True
        assert retry_after is None

    def test_requests_within_limit_all_allowed(self, limiter):
        for _ in range(5):
            allowed, _ = limiter.is_allowed("10.0.0.1")
            assert allowed is True

    def test_request_beyond_limit_rejected(self, limiter):
        for _ in range(5):
            limiter.is_allowed("10.0.0.2")
        allowed, retry_after = limiter.is_allowed("10.0.0.2")
        assert allowed is False
        assert retry_after is not None
        assert retry_after >= 1

    def test_different_identifiers_tracked_independently(self, limiter):
        for _ in range(5):
            limiter.is_allowed("host-a")
        # host-a is now rate-limited; host-b should still be free
        allowed_b, _ = limiter.is_allowed("host-b")
        assert allowed_b is True

    def test_retry_after_is_positive_integer(self, tight_limiter):
        tight_limiter.is_allowed("client-x")
        tight_limiter.is_allowed("client-x")
        allowed, retry_after = tight_limiter.is_allowed("client-x")
        assert allowed is False
        assert isinstance(retry_after, int)
        assert retry_after >= 1

    def test_retry_after_does_not_exceed_window(self, tight_limiter):
        tight_limiter.is_allowed("client-y")
        tight_limiter.is_allowed("client-y")
        _, retry_after = tight_limiter.is_allowed("client-y")
        assert retry_after <= tight_limiter.window_seconds + 1

    def test_redis_key_is_namespaced(self, limiter):
        """Verify the key uses the rate_limit: prefix to avoid collisions."""
        limiter.is_allowed("user-1")
        key = limiter._get_key("user-1")
        assert key == "rate_limit:user-1"


class TestGetRemaining:
    def test_full_quota_before_any_request(self, limiter):
        remaining = limiter.get_remaining("fresh-ip")
        assert remaining == 5

    def test_remaining_decreases_with_requests(self, limiter):
        limiter.is_allowed("ip-2")
        limiter.is_allowed("ip-2")
        assert limiter.get_remaining("ip-2") == 3

    def test_remaining_is_zero_when_exhausted(self, limiter):
        for _ in range(5):
            limiter.is_allowed("ip-3")
        assert limiter.get_remaining("ip-3") == 0

    def test_remaining_never_negative(self, limiter):
        for _ in range(7):
            limiter.is_allowed("ip-4")
        assert limiter.get_remaining("ip-4") == 0
