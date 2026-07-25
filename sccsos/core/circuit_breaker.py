"""Production-grade circuit breaker pattern — thread-safe, three-state.

Provides a standalone CircuitBreaker utility with no dependencies on
Kafka or event bus internals.  Suitable for wrapping any external
service call that may transiently fail.

State machine::

    CLOSED ──(N failures)──▶ OPEN ──(timeout)──▶ HALF_OPEN
      ▲                                               │
      └─────────(success)─────────────────────────────┘
      ◀──(failure)── OPEN
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("sccsos.circuit_breaker")


class CircuitBreakerState(str, Enum):
    """Circuit breaker lifecycle states.

    .. code-block::

        CLOSED ──(N failures)──▶ OPEN ──(timeout)──▶ HALF_OPEN
          ▲                                               │
          └─────────(success)─────────────────────────────┘
          ◀──(failure)── OPEN
    """
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is OPEN and fast-failing."""


class CircuitBreaker:
    """Production-grade circuit breaker for remote service calls.

    Thread-safe: all state transitions are protected by a reentrant lock.

    Args:
        failure_threshold: Consecutive failures before opening the circuit.
        recovery_timeout: Seconds to wait before transitioning to HALF_OPEN.
        half_open_max_requests: Successful probes needed to close the circuit.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_requests: int = 3,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_requests = half_open_max_requests

        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_successes: int = 0
        self._total_failures: int = 0
        self._total_successes: int = 0
        self._state_changes: int = 0
        self._lock = threading.Lock()

    # ── Properties ─────────────────────────────────────────────────

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def metrics(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self._failure_threshold,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "state_changes": self._state_changes,
            "recovery_timeout_s": self._recovery_timeout,
        }

    # ── Core ───────────────────────────────────────────────────────

    def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute *fn* through the circuit breaker.

        Returns:
            The return value of *fn*.

        Raises:
            CircuitBreakerOpenError: If the circuit is OPEN and not yet
                ready for recovery.
            Any exception raised by *fn* is propagated; the circuit
                breaker records it as a failure.
        """
        # Pre-flight: check circuit state
        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if time.monotonic() - self._last_failure_time < self._recovery_timeout:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker OPEN (failures={self._failure_count}, "
                        f"retry in {self._recovery_timeout - (time.monotonic() - self._last_failure_time):.0f}s)"
                    )
                # Timeout elapsed → transition to HALF_OPEN
                self._state = CircuitBreakerState.HALF_OPEN
                self._half_open_successes = 0
                self._state_changes += 1
                logger.info(
                    "Circuit breaker OPEN→HALF_OPEN after %.0fs timeout",
                    self._recovery_timeout,
                )

            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_successes >= self._half_open_max_requests:
                    raise CircuitBreakerOpenError(
                        "Circuit breaker HALF_OPEN (awaiting recovery verification)"
                    )

        # Execute
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            with self._lock:
                self._failure_count += 1
                self._total_failures += 1
                self._last_failure_time = time.monotonic()
                if self._state == CircuitBreakerState.HALF_OPEN:
                    self._state = CircuitBreakerState.OPEN
                    self._state_changes += 1
                    logger.warning(
                        "Circuit breaker HALF_OPEN→OPEN (probe failed: %s)", e,
                    )
                elif self._failure_count >= self._failure_threshold:
                    self._state = CircuitBreakerState.OPEN
                    self._state_changes += 1
                    logger.warning(
                        "Circuit breaker CLOSED→OPEN after %d failures (last: %s)",
                        self._failure_count, e,
                    )
                else:
                    logger.debug(
                        "Circuit breaker recorded failure %d/%d: %s",
                        self._failure_count, self._failure_threshold, e,
                    )
            raise

        # Success
        with self._lock:
            self._failure_count = 0
            self._total_successes += 1
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self._half_open_max_requests:
                    self._state = CircuitBreakerState.CLOSED
                    self._state_changes += 1
                    logger.info(
                        "Circuit breaker HALF_OPEN→CLOSED (%d/%d probes succeeded)",
                        self._half_open_successes, self._half_open_max_requests,
                    )
        return result

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED."""
        with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0
            self._half_open_successes = 0
            logger.info("Circuit breaker manually reset to CLOSED")
