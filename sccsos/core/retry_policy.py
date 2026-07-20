"""RetryPolicy — configurable exponential-backoff retry for workflow steps.

Usage:

    policy = RetryPolicy(db, db_lock)
    result = policy.execute(
        fn=lambda: delegate_to_agent(step),
        step_id=step.id,
        step_agent=step.agent,
        max_attempts=1 + step.retry,
        cancel_event=cancel_event,
    )

Thread-safe: all DB writes are serialized under the injected ``db_lock``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from sccsos.core.db import Database
from sccsos.core.db import crud


class RetryPolicy:
    """Exponential-backoff retry with cancellation, policy-fast-fail, and DB event logging."""

    def __init__(self, db, db_lock: threading.Lock,
                 base_delay: int = 1, max_delay: int = 30):
        self._db = db
        self._db_lock = db_lock
        self._base_delay = base_delay
        self._max_delay = max_delay

    def execute(
        self,
        fn: Callable[[], Any],
        step_id: str = "",
        step_agent: str = "",
        max_attempts: int = 1,
        cancel_event: Optional[threading.Event] = None,
        non_retryable_patterns: tuple[str, ...] = ("Policy rejected", "cancelled"),
    ) -> Any:
        """Execute ``fn`` with exponential-backoff retry.

        Args:
            fn: Zero-argument callable to execute.
            step_id: Step ID for error messages and event logging.
            step_agent: Agent name for event logging.
            max_attempts: Maximum attempts (1 initial + N-1 retries).
            cancel_event: Optional cancellation signal.
            non_retryable_patterns: Substrings that signal a non-retryable failure.

        Returns:
            The return value of ``fn``.

        Raises:
            WorkflowExecutionError: On non-retryable failure or exhausted attempts.
        """
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            # Check cancellation before each attempt
            if cancel_event and cancel_event.is_set():
                from sccsos.core.step_executor import WorkflowExecutionError
                raise WorkflowExecutionError(
                    f"Step '{step_id}' cancelled after {attempt} attempt(s)"
                )

            try:
                return fn()

            except Exception as e:
                # Check if this is a non-retryable failure
                estr = str(e).lower() if str(e) else ""
                if any(p.lower() in estr for p in non_retryable_patterns):
                    raise

                last_error = e
                if attempt < max_attempts - 1:
                    delay = min(self._base_delay ** attempt, self._max_delay)
                    # Log retry via DB event (skip if no DB)
                    if self._db is not None:
                        with self._db_lock:
                            crud.add_event(
                                self._db,
                                step_agent,
                                "retry",
                                f"Step '{step_id}' attempt {attempt + 1}/{max_attempts} "
                                f"failed, retrying in {delay}s: {str(e)[:200]}",
                            )
                    time.sleep(delay)

        # All attempts exhausted
        from sccsos.core.step_executor import WorkflowExecutionError
        raise WorkflowExecutionError(
            f"Step '{step_id}' failed after {max_attempts} attempts: {last_error}"
        ) from last_error
