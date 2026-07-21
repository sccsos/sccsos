"""Remote Hermes Adapter — Hermes CLI via HTTP API proxy.

Delegates tasks to a remote Hermes Agent instance via HTTP,
enabling distributed deployment where SCCS OS runs centrally
and Hermes Agents run on remote worker nodes.

Usage::

    from sccsos.core.hermes_remote_adapter import RemoteHermesAdapter

    adapter = RemoteHermesAdapter(
        url="http://hermes-node:8080",
        token="my-secret-token",
    )
    result = adapter.delegate_task(
        agent_name="architect",
        prompt="设计一个认证模块",
    )
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Optional

from sccsos.core.hermes_adapter import (
    HermesAdapter,
    TaskResult,
    _estimate_tokens,
)

logger = __import__("logging").getLogger("sccsos.hermes_remote_adapter")


class RemoteHermesAdapter(HermesAdapter):
    """Hermes adapter that delegates via HTTP to a remote Hermes proxy.

    The remote proxy is expected to expose a REST API that accepts
    a JSON payload and returns a JSON response with the task output.

    API contract (remote proxy must implement)::

        POST /api/v1/delegate
        Headers:
          Authorization: Bearer <token>
          Content-Type: application/json
        Body: {
          "agent_name": "...",
          "prompt": "...",
          "profile": "sccsos",
          "model": "deepseek-v4-flash"
        }
        Response 200: {
          "response": "Agent output text",
          "duration_ms": 1234,
          "tokens_input": 100,
          "tokens_output": 50,
          "model": "deepseek-v4-flash",
          "cost_usd": 0.0012,
          "success": true,
          "error": ""
        }
    """

    def __init__(
        self,
        url: str = "http://localhost:8080",
        token: str = "",
        timeout: int = 60,
        retry_count: int = 2,
    ):
        self._url = url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._retry_count = retry_count
        self._delegate_endpoint = f"{self._url}/api/v1/delegate"

    def delegate_task(
        self,
        agent_name: str,
        prompt: str,
        profile: str = "sccsos",
        model: Optional[str] = None,
        policy_engine=None,
        cancel_event: threading.Event | None = None,
        timeout: int = 300,
    ) -> TaskResult:
        """Delegate via HTTP POST to the remote Hermes proxy.

        Args:
            agent_name: Name of the target agent.
            prompt: The prompt text.
            profile: Hermes profile name (passed to remote proxy).
            model: Optional model override.
            policy_engine: Optional PolicyEngine for pre-flight checks.
            cancel_event: Optional threading.Event for cancellation.
            timeout: Max seconds per HTTP request (default 300).

        Returns:
            TaskResult with the remote agent's response.
        """
        # ── Policy pre-flight ────────────────────────────────────
        policy_error = self._policy_preflight(agent_name, prompt, model, policy_engine)
        if policy_error:
            return policy_error

        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "prompt": prompt,
            "profile": profile,
        }
        if model:
            payload["model"] = model

        start_time = time.time()
        last_error = ""
        effective_timeout = min(timeout, self._timeout)

        for attempt in range(self._retry_count + 1):
            if cancel_event is not None and cancel_event.is_set():
                duration_ms = int((time.time() - start_time) * 1000)
                return TaskResult(
                    response="",
                    duration_ms=duration_ms,
                    success=False,
                    error=f"Task cancelled (agent: {agent_name})",
                )

            result = self._send_request(payload, effective_timeout, attempt)
            if result.success or (
                result.error and result.error.startswith("HTTP ")
            ):
                return result

            last_error = result.error
            if attempt < self._retry_count:
                time.sleep(min(2**attempt, 10))
                continue

        return TaskResult(
            response="",
            duration_ms=int((time.time() - start_time) * 1000),
            success=False,
            error=f"Remote task failed after {self._retry_count + 1} attempts: {last_error}",
        )

    def _send_request(
        self, payload: dict[str, Any], timeout: int, attempt: int
    ) -> TaskResult:
        """Send a single HTTP request to the remote Hermes proxy."""
        try:
            import httpx

            headers = {
                "Content-Type": "application/json",
            }
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"

            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    self._delegate_endpoint,
                    json=payload,
                    headers=headers,
                )

            duration_ms = int(resp.elapsed.total_seconds() * 1000) if hasattr(resp, "elapsed") else 0

            if resp.status_code == 200:
                data = resp.json()
                tokens_in = data.get("tokens_input", 0)
                tokens_out = data.get("tokens_output", 0)
                if not tokens_in and not tokens_out:
                    prompt_text = payload.get("prompt", "")
                    response_text = data.get("response", "")
                    tokens_in, tokens_out = _estimate_tokens(prompt_text, response_text)
                return TaskResult(
                    response=data.get("response", ""),
                    duration_ms=data.get("duration_ms", duration_ms),
                    tokens_input=tokens_in,
                    tokens_output=tokens_out,
                    model=data.get("model", payload.get("model", "")),
                    cost_usd=float(data.get("cost_usd", 0.0)),
                    success=data.get("success", True),
                    error=data.get("error", ""),
                )
            else:
                error_body = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"
                return TaskResult(
                    response="",
                    duration_ms=duration_ms,
                    success=False,
                    error=f"HTTP {resp.status_code}: {error_body}",
                )

        except ImportError:
            return TaskResult(
                response="",
                success=False,
                error="httpx library required. Install with: pip install sccsos[remote]",
            )
        except httpx.TimeoutException:
            return TaskResult(
                response="",
                success=False,
                error=f"Remote proxy timeout (attempt {attempt + 1})",
            )
        except httpx.ConnectError:
            return TaskResult(
                response="",
                success=False,
                error=f"Cannot connect to remote proxy at {self._url} (attempt {attempt + 1})",
            )
        except Exception as e:
            return TaskResult(
                response="",
                success=False,
                error=f"Remote request failed: {e}",
            )

    def _policy_preflight(
        self, agent_name: str, prompt: str,
        model: Optional[str], policy_engine,
    ) -> Optional[TaskResult]:
        """Run policy pre-flight checks. Returns TaskResult if blocked, None if OK."""
        if policy_engine is None:
            return None
        from sccsos.security.policy import PolicyViolation

        estimated_cost = max(0.001, (len(prompt) / 3.5) * 0.000_000_28 * 2)
        result = policy_engine.check_delegation(
            agent_name=agent_name,
            model=model or "deepseek-v4-flash",
            estimated_cost=estimated_cost,
        )
        if not result.allowed:
            return TaskResult(
                response="",
                success=False,
                error=f"Policy rejected: {result.reason}",
            )

        tool_result = policy_engine.check_tool_access(
            agent_name, "delegate_task"
        )
        if not tool_result.allowed:
            return TaskResult(
                response="",
                success=False,
                error=f"Tool rejected: {tool_result.reason}",
            )
        return None

    def check_connectivity(self) -> bool:
        """Check if the remote Hermes proxy is reachable."""
        try:
            import httpx
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    f"{self._url}/api/v1/health",
                    headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
                )
                return resp.status_code == 200
        except Exception:
            return False

    def get_profile_info(self, profile: str = "sccsos") -> dict:
        """Get profile info from the remote Hermes proxy."""
        try:
            import httpx
            headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
            with httpx.Client(timeout=10) as client:
                resp = client.post(
                    f"{self._url}/api/v1/profile",
                    json={"profile": profile},
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "profile": profile,
                        "info": data.get("info", ""),
                        "remote_url": self._url,
                    }
                return {
                    "profile": profile,
                    "error": f"HTTP {resp.status_code}",
                    "remote_url": self._url,
                }
        except Exception as e:
            return {
                "profile": profile,
                "error": str(e),
                "remote_url": self._url,
            }
