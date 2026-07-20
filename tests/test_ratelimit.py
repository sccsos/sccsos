"""Tests for RateLimiter — token-bucket rate limiting.

Tests cover:
  - Bucket: construction, refill, consume, reset, token queries
  - RateLimiter: basic check, burst, multi-key isolation
  - Disabled mode (tokens_per_minute=0)
  - reset_key, periodic cleanup
  - Thread safety (basic)
"""

from __future__ import annotations

import threading
import time

import pytest

from sccsos.security.ratelimit import Bucket, RateLimiter, RateLimitResult


# ── Bucket Unit Tests ────────────────────────────────────────────────


class TestBucket:
    """Token bucket mechanics — the core data structure of RateLimiter."""

    def test_construction(self):
        b = Bucket(capacity=10, refill_rate=1.0)
        assert b.capacity == 10
        assert b.refill_rate == 1.0
        assert b.tokens == 10.0  # Starts full
        assert b.remaining_tokens == 10

    def test_consume_reduces_tokens(self):
        b = Bucket(capacity=10, refill_rate=100.0)
        assert b.consume(3)
        assert b.remaining_tokens == 7

    def test_consume_returns_false_when_empty(self):
        b = Bucket(capacity=5, refill_rate=0.0)  # No refill
        assert b.consume(5)  # Uses all tokens
        assert not b.consume(1)  # Should fail
        assert b.remaining_tokens == 0

    def test_refill_over_time(self):
        """Tokens should refill after time passes (with high refill rate)."""
        b = Bucket(capacity=10, refill_rate=10.0)  # 10 tokens/sec
        b.consume(10)  # Drain
        assert b.remaining_tokens == 0

        # Record bucket state's last_refill, advance time
        b.last_refill = time.monotonic() - 1.0  # Pretend 1 second passed
        assert b.remaining_tokens >= 9  # Should have refilled ~10 tokens

    def test_refill_does_not_exceed_capacity(self):
        b = Bucket(capacity=5, refill_rate=100.0)
        b.last_refill = time.monotonic() - 10.0  # 10 seconds of refill
        assert b.remaining_tokens <= 5  # Capped at capacity

    def test_reset(self):
        b = Bucket(capacity=10, refill_rate=0.0)
        b.consume(7)
        assert b.remaining_tokens == 3
        b.reset()
        assert b.remaining_tokens == 10

    def test_seconds_until_full(self):
        b = Bucket(capacity=10, refill_rate=2.0)  # 2 tokens/sec
        assert b.seconds_until_full == 0.0  # Already full

        b.consume(5)
        secs = b.seconds_until_full
        assert 2.0 <= secs <= 3.0  # Need 5 tokens / 2 per sec = 2.5s

    def test_seconds_until_full_zero_rate(self):
        b = Bucket(capacity=10, refill_rate=0.0)
        b.consume(5)
        assert b.seconds_until_full == 0.0  # No refill possible

    def test_remaining_tokens_refills_before_returning(self):
        """remaining_tokens should trigger refill before returning."""
        b = Bucket(capacity=10, refill_rate=10.0)
        b.consume(10)
        b.last_refill = time.monotonic() - 0.5
        tokens = b.remaining_tokens
        assert tokens >= 5


# ── RateLimiter Unit Tests ───────────────────────────────────────────


class TestRateLimiter:
    """Rate limit orchestration — multi-key isolation, burst, cleanup."""

    def test_construction_defaults(self):
        limiter = RateLimiter(tokens_per_minute=60)
        assert limiter.is_enabled
        assert limiter._capacity == 60
        assert limiter._refill_rate == 1.0  # 60/60 = 1 token/sec

    def test_construction_zero_rate_disabled(self):
        limiter = RateLimiter(tokens_per_minute=0)
        assert not limiter.is_enabled

    def test_check_basic_allowed(self):
        limiter = RateLimiter(tokens_per_minute=60)
        result = limiter.check("agent:test")
        assert result.allowed
        assert result.remaining >= 59  # Just consumed 1
        assert 0 <= result.reset_after <= 61

    def test_check_consumes_token(self):
        limiter = RateLimiter(tokens_per_minute=10, burst_capacity=10)
        for _ in range(10):
            assert limiter.check("agent:test").allowed
        # 11th should be denied (bucket empty, no time for refill)
        result = limiter.check("agent:test")
        assert not result.allowed
        assert result.remaining == 0

    def test_burst_capacity(self):
        """Burst capacity can exceed tokens_per_minute."""
        limiter = RateLimiter(tokens_per_minute=10, burst_capacity=20)
        for _ in range(20):
            assert limiter.check("agent:burst").allowed
        # 21st should be denied
        assert not limiter.check("agent:burst").allowed

    def test_burst_defaults_to_tokens_per_minute(self):
        """When burst_capacity is None, it equals tokens_per_minute."""
        limiter = RateLimiter(tokens_per_minute=30)
        assert limiter._capacity == 30

    def test_multi_key_isolation(self):
        """Different keys should have independent buckets."""
        limiter = RateLimiter(tokens_per_minute=5, burst_capacity=5)
        for _ in range(5):
            assert limiter.check("agent:a").allowed
        # Key 'a' should be exhausted
        assert not limiter.check("agent:a").allowed
        # Key 'b' should still have capacity (at least 3 remaining)
        result_b = limiter.check("agent:b")
        assert result_b.allowed
        assert result_b.remaining >= 3  # Just consumed 1 of 5

    def test_disabled_mode(self):
        """When tokens_per_minute=0, all requests are allowed."""
        limiter = RateLimiter(tokens_per_minute=0)
        for _ in range(100):
            result = limiter.check("agent:flood")
            assert result.allowed
            assert result.remaining == 9999

    def test_reset_key(self):
        """reset_key should restore a specific key's bucket to full."""
        limiter = RateLimiter(tokens_per_minute=5, burst_capacity=5)
        for _ in range(5):
            limiter.check("agent:test")
        assert not limiter.check("agent:test").allowed

        limiter.reset_key("agent:test")
        assert limiter.check("agent:test").allowed  # Recovered

    def test_reset_key_nonexistent(self):
        """reset_key on a key that doesn't exist should not crash."""
        limiter = RateLimiter(tokens_per_minute=60)
        limiter.reset_key("nonexistent")  # Should not raise

    def test_custom_token_cost(self):
        """check() should support consuming multiple tokens per call."""
        limiter = RateLimiter(tokens_per_minute=10, burst_capacity=10)
        assert limiter.check("agent:cost", tokens=7).allowed
        assert limiter.check("agent:cost", tokens=3).allowed
        # 11th token should fail
        assert not limiter.check("agent:cost", tokens=1).allowed

    def test_periodic_cleanup_removes_idle_buckets(self):
        """Fully refilled, idle buckets should be cleaned up."""
        limiter = RateLimiter(
            tokens_per_minute=60, burst_capacity=10, cleanup_interval=0.0
        )
        limiter.check("agent:temp")  # Creates bucket, consumes 1

        # Force last_cleanup far in the past so cleanup triggers
        limiter._last_cleanup = time.monotonic() - 1.0

        # Make the bucket obviously idle by letting it refill fully
        # Fast-forward the bucket's last_refill so it appears long-idle
        bucket = limiter._buckets["agent:temp"]
        bucket.last_refill = time.monotonic() - 60.0  # 1 minute ago
        bucket.tokens = 10.0  # Full

        limiter._periodic_cleanup()
        assert "agent:temp" not in limiter._buckets  # Cleaned up

    def test_cleanup_keeps_active_buckets(self):
        """Partially consumed buckets should survive cleanup."""
        limiter = RateLimiter(
            tokens_per_minute=60, burst_capacity=10, cleanup_interval=0.0
        )
        limiter.check("agent:active")
        limiter.check("agent:active")
        limiter.check("agent:active")  # 7 remaining

        limiter._last_cleanup = time.monotonic() - 1.0
        limiter._periodic_cleanup()
        assert "agent:active" in limiter._buckets  # Still active

    def test_cleanup_interval_respected(self):
        """_periodic_cleanup should skip if interval hasn't elapsed."""
        limiter = RateLimiter(
            tokens_per_minute=60, cleanup_interval=9999  # Very long
        )
        limiter.check("agent:temp")
        limiter._last_cleanup = time.monotonic() - 100  # But interval is huge
        # Should not clean up — interval hasn't elapsed relative to last cleanup
        # Actually, last_cleanup is old, so next cleanup will trigger
        with pytest.MonkeyPatch.context() as m:
            # Simulate that we just had a recent cleanup
            limiter._last_cleanup = time.monotonic()
            limiter._periodic_cleanup()
            assert "agent:temp" in limiter._buckets

    def test_result_dataclass(self):
        """RateLimitResult should carry standard fields."""
        r = RateLimitResult(allowed=True, remaining=42, reset_after=3.5)
        assert r.allowed
        assert r.remaining == 42
        assert r.reset_after == 3.5

    def test_thread_safety(self):
        """Concurrent access should not cause race conditions."""
        limiter = RateLimiter(tokens_per_minute=1000, burst_capacity=1000)
        errors = []

        def hammer():
            try:
                for _ in range(100):
                    limiter.check("agent:shared")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
