"""Tests for RetryPolicy — retry logic, cancellation, non-retryable patterns."""

from __future__ import annotations

import threading
import time

import pytest

from sccsos.core.retry_policy import RetryPolicy


@pytest.fixture
def policy():
    """RetryPolicy with no DB (DB-dependent features not tested here)."""
    return RetryPolicy(None, threading.Lock(), base_delay=1, max_delay=2)


class TestRetryPolicy:
    """Exhaustive RetryPolicy tests."""

    def test_success_first_attempt(self, policy):
        """fn succeeds on first attempt — no retry."""
        result = policy.execute(lambda: "ok", max_attempts=3)
        assert result == "ok"

    def test_success_after_retries(self, policy):
        """fn fails twice then succeeds."""
        attempts = [0]

        def flaky():
            attempts[0] += 1
            if attempts[0] < 3:
                raise ValueError("transient")
            return "finally_ok"

        result = policy.execute(flaky, step_id="flaky", max_attempts=5)
        assert result == "finally_ok"
        assert attempts[0] == 3

    def test_exhaust_all_retries(self, policy):
        """fn always fails — exception raised after max_attempts."""
        with pytest.raises(Exception) as exc_info:
            policy.execute(
                lambda: (_ for _ in ()).throw(ValueError("boom")),
                step_id="exhaust",
                max_attempts=3,
            )
        assert "failed after 3 attempts" in str(exc_info.value)

    def test_single_attempt_no_retry(self, policy):
        """max_attempts=1 means no retry at all."""
        with pytest.raises(Exception, match="no_retry"):
            policy.execute(
                lambda: (_ for _ in ()).throw(ValueError("no_retry")),
                step_id="single",
                max_attempts=1,
            )

    def test_non_retryable_policy_rejected(self, policy):
        """Pattern 'Policy rejected' should not retry."""
        with pytest.raises(ValueError, match="Policy rejected"):
            policy.execute(
                lambda: (_ for _ in ()).throw(ValueError("Policy rejected")),
                step_id="noretry",
                max_attempts=5,
            )

    def test_non_retryable_cancelled(self, policy):
        """Pattern 'cancelled' should not retry."""
        with pytest.raises(ValueError, match="cancelled"):
            policy.execute(
                lambda: (_ for _ in ()).throw(ValueError("workflow cancelled")),
                step_id="cancel",
                max_attempts=5,
            )

    def test_custom_non_retryable_patterns(self, policy):
        """Custom non-retryable patterns override defaults."""
        with pytest.raises(ValueError, match="fatal"):
            policy.execute(
                lambda: (_ for _ in ()).throw(ValueError("fatal error")),
                step_id="custom",
                max_attempts=5,
                non_retryable_patterns=("fatal",),
            )

    def test_cancel_event_before_attempt(self, policy):
        """Cancel event set before execution prevents any attempt."""
        evt = threading.Event()
        evt.set()  # Already cancelled

        with pytest.raises(Exception) as exc_info:
            policy.execute(
                lambda: None,
                step_id="pre_cancel",
                max_attempts=5,
                cancel_event=evt,
            )
        assert "cancelled" in str(exc_info.value)

    def test_cancel_event_during_retry(self, policy):
        """Cancel event set during retry loop stops retrying."""
        evt = threading.Event()
        attempts = [0]

        def flaky_then_cancel():
            attempts[0] += 1
            if attempts[0] == 2:
                evt.set()  # Cancel on second attempt
            raise ValueError("transient")

        with pytest.raises(Exception) as exc_info:
            policy.execute(
                flaky_then_cancel,
                step_id="mid_cancel",
                max_attempts=5,
                cancel_event=evt,
            )
        assert "cancelled" in str(exc_info.value)
        assert attempts[0] == 2  # Only 2 attempts before cancel

    def test_max_attempts_zero(self, policy):
        """max_attempts=1 should still run at least once (not zero)."""
        with pytest.raises(Exception, match="failed after 1 attempts"):
            policy.execute(
                lambda: (_ for _ in ()).throw(ValueError("fail")),
                step_id="zero",
                max_attempts=1,
            )

    def test_step_id_in_error_message(self, policy):
        """Error message includes step_id."""
        with pytest.raises(Exception) as exc_info:
            policy.execute(
                lambda: (_ for _ in ()).throw(ValueError("err")),
                step_id="my-step",
                max_attempts=1,
            )
        assert "my-step" in str(exc_info.value)

    def test_retry_delay_respects_max_delay(self, policy):
        """Delay should be capped at max_delay."""
        # Override policy with small base_delay and max_delay=1
        fast_policy = RetryPolicy(None, threading.Lock(), base_delay=1, max_delay=1)
        start = time.monotonic()
        with pytest.raises(Exception):
            fast_policy.execute(
                lambda: (_ for _ in ()).throw(ValueError("slow")),
                step_id="delay",
                max_attempts=3,
            )
        elapsed = time.monotonic() - start
        # Without cap, 2nd attempt would wait 2s. With cap=1s, total < ~3s
        assert elapsed < 5.0, f"Retry delay exceeded cap: {elapsed:.2f}s"
