"""RateLimiter — token-bucket rate limiter per agent/tenant.

Provides per-agent and per-tenant rate limiting to prevent runaway
resource consumption.  Uses a token-bucket algorithm (leaky bucket
equivalent) with configurable refill rate and capacity.

Usage:
    limiter = RateLimiter(tokens_per_minute=60, burst_capacity=10)
    ok = limiter.check("agent:architect")
    ok = limiter.check("tenant:default")
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool = True
    remaining: int = 0
    reset_after: float = 0.0  # seconds until bucket refills


class Bucket:
    """Token bucket for a single key (agent/tenant)."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()

    def refill(self) -> None:
        """Add tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from the bucket.

        Returns:
            True if tokens were consumed, False if rate limited.
        """
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def reset(self) -> None:
        """Reset the bucket to full capacity."""
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()

    @property
    def remaining_tokens(self) -> int:
        """Return the current number of available tokens."""
        self.refill()
        return int(self.tokens)

    @property
    def seconds_until_full(self) -> float:
        """Return seconds until the bucket is completely refilled."""
        deficit = self.capacity - self.remaining_tokens
        if deficit <= 0 or self.refill_rate <= 0:
            return 0.0
        return deficit / self.refill_rate


class RateLimiter:
    """Token-bucket rate limiter with per-key isolation.

    Args:
        tokens_per_minute: Max requests per minute per key.
            Set to 0 to disable rate limiting.
        burst_capacity: Max burst size (default = tokens_per_minute).
        cleanup_interval: Seconds between stale bucket cleanups.
    """

    def __init__(self, tokens_per_minute: int = 60,
                 burst_capacity: Optional[int] = None,
                 cleanup_interval: float = 300.0):
        self._refill_rate = tokens_per_minute / 60.0 if tokens_per_minute > 0 else 0
        self._capacity = burst_capacity or tokens_per_minute or 60
        self._cleanup_interval = cleanup_interval
        self._lock = threading.Lock()
        self._buckets: dict[str, Bucket] = {}
        self._last_cleanup = time.monotonic()

    @property
    def is_enabled(self) -> bool:
        return self._refill_rate > 0

    def check(self, key: str, tokens: int = 1) -> RateLimitResult:
        """Check if an operation is allowed under the rate limit.

        Args:
            key: Rate limit key (e.g. ``"agent:architect"``,
                ``"tenant:default"``).
            tokens: Token cost of this operation (default 1).

        Returns:
            RateLimitResult with allowed/remaining/reset_after.
        """
        if not self.is_enabled:
            return RateLimitResult(allowed=True, remaining=9999)

        with self._lock:
            self._periodic_cleanup()

            if key not in self._buckets:
                self._buckets[key] = Bucket(self._capacity, self._refill_rate)

            bucket = self._buckets[key]
            allowed = bucket.consume(tokens)

            return RateLimitResult(
                allowed=allowed,
                remaining=bucket.remaining_tokens,
                reset_after=bucket.seconds_until_full,
            )

    def reset_key(self, key: str) -> None:
        """Reset the bucket for a specific key."""
        with self._lock:
            if key in self._buckets:
                self._buckets[key].reset()

    def _periodic_cleanup(self) -> None:
        """Remove stale buckets to prevent memory leaks."""
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        stale_keys = [
            k for k, b in self._buckets.items()
            if b.remaining_tokens >= b.capacity  # Fully refilled → idle
        ]
        for k in stale_keys:
            del self._buckets[k]
