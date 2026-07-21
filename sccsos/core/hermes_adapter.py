"""Hermes Adapter — bridge to the Hermes Agent CLI.

Provides an abstract interface (ABC) for Hermes API calls, with a
subprocess-based implementation and a mock for testing.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TaskResult:
    """Result of a delegated task with observability data."""
    response: str
    duration_ms: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    model: str = "deepseek-v4-flash"
    cost_usd: float = 0.0
    success: bool = True
    error: str = ""


# ── Abstract Interface ─────────────────────────────────────────────


class HermesAdapter(ABC):
    """Abstract interface for Hermes Agent interactions."""

    @abstractmethod
    def delegate_task(self, agent_name: str, prompt: str,
                      profile: str = "sccsos",
                      model: Optional[str] = None,
                      policy_engine=None,
                      cancel_event: "threading.Event | None" = None,
                      timeout: int = 300) -> TaskResult:
        """Delegate a task to an agent. Returns TaskResult with response and metadata.

        Args:
            agent_name: Name of the agent to delegate to.
            prompt: The prompt text.
            profile: Hermes profile name.
            model: Optional model override.
            policy_engine: Optional PolicyEngine for pre-flight checks.
            cancel_event: Optional threading.Event. When set, the running
                subprocess is killed and the task is marked as cancelled.
            timeout: Max seconds to wait for the subprocess (default 300).
        """
        ...

    @abstractmethod
    def check_connectivity(self) -> bool:
        """Check if Hermes CLI is available."""
        ...

    @abstractmethod
    def get_profile_info(self, profile: str = "sccsos") -> dict:
        """Get profile configuration info."""
        ...


# ── Subprocess Implementation ──────────────────────────────────────


class HermesSubprocessAdapter(HermesAdapter):
    """Hermes adapter using the hermes CLI via subprocess.

    Supports optional CommandWhitelist sandbox — every subprocess
    call is checked for dangerous patterns and whitelist compliance
    before execution.
    """

    def __init__(self, hermes_bin: str = "hermes",
                 whitelist: Optional["CommandWhitelist"] = None,
                 retry_count: int = 2):
        self._hermes_bin = hermes_bin
        self._whitelist = whitelist
        self._retry_count = retry_count

    def _sandbox_check(self, cmd: list[str]) -> str | None:
        """Run sandbox check. Returns error string if blocked, None if allowed."""
        if self._whitelist is None:
            return None
        from sccsos.security.sandbox import SandboxViolation
        cmd_str = shlex.join(cmd)
        result = self._whitelist.check(cmd_str)
        if not result.allowed:
            return result.reason
        return None

    def delegate_task(self, agent_name: str, prompt: str,
                      profile: str = "sccsos",
                      model: Optional[str] = None,
                      policy_engine=None,
                      cancel_event: threading.Event | None = None,
                      timeout: int = 300) -> TaskResult:
        """Delegate via `hermes -p <profile> -z <prompt>`.

        Runs a pre-delegation policy check if policy_engine is provided.
        When cancel_event is set, kills the running subprocess and
        returns a cancelled TaskResult.
        """
        # ── Policy pre-flight ─────────────────────────────────────
        policy_error = self._policy_preflight(agent_name, prompt, model, policy_engine)
        if policy_error:
            return policy_error

        cmd = [self._hermes_bin, "-p", profile, "-z", prompt]
        if model:
            cmd.extend(["-m", model])

        # ── Sandbox pre-flight ─────────────────────────────────────
        sandbox_error = self._sandbox_check(cmd)
        if sandbox_error:
            return TaskResult(
                response="",
                success=False,
                error=f"Sandbox blocked: {sandbox_error}",
            )

        start_time = time.time()
        # ── Subprocess execution with retry for transient failures ──
        max_attempts = self._retry_count + 1
        last_error = ""
        for attempt in range(max_attempts):
            # Check cancellation before each attempt
            if cancel_event is not None and cancel_event.is_set():
                duration_ms = int((time.time() - start_time) * 1000)
                return TaskResult(
                    response="",
                    duration_ms=duration_ms,
                    success=False,
                    error=f"Task cancelled (agent: {agent_name})",
                )

            result = self._run_single_attempt(
                cmd, agent_name, cancel_event, start_time, timeout,
                prompt=prompt,
            )

            # If succeeded or permanent failure, return immediately
            if result.success or result.error.startswith("Hermes CLI"):
                return result

            # If timed out or transient failure, record and retry
            last_error = result.error
            if attempt < max_attempts - 1:
                time.sleep(min(2 ** attempt, 10))
                continue
            return result

        # All attempts exhausted
        return TaskResult(
            response="",
            success=False,
            error=f"Task failed after {max_attempts} attempts: {last_error}",
        )

    def _policy_preflight(
        self, agent_name: str, prompt: str,
        model: Optional[str], policy_engine,
    ) -> Optional[TaskResult]:
        """Run policy pre-flight checks. Returns TaskResult if blocked, None if OK."""
        if policy_engine is None:
            return None
        from sccsos.security.policy import PolicyViolation

        # Budget check
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

        # Tool access check — defense-in-depth
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

    def _run_single_attempt(
        self, cmd: list[str], agent_name: str,
        cancel_event: threading.Event | None,
        start_time: float, timeout: int, prompt: str = "",
    ) -> TaskResult:
        """Run a single subprocess attempt. Returns a TaskResult.

        Handles spawn, poll-with-cancel, timeout, stdout/stderr parsing,
        and token estimation.
        """
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Poll with cancel_event check (1s intervals)
            deadline = start_time + timeout
            while time.time() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    proc.kill()
                    proc.wait(timeout=5)
                    duration_ms = int((time.time() - start_time) * 1000)
                    return TaskResult(
                        response="",
                        duration_ms=duration_ms,
                        success=False,
                        error=f"Task cancelled (agent: {agent_name})",
                    )
                ret = proc.poll()
                if ret is not None:
                    break
                time.sleep(0.5)
            else:
                # Deadline reached — kill and timeout
                proc.kill()
                proc.wait(timeout=5)
                duration_ms = int((time.time() - start_time) * 1000)
                return TaskResult(
                    response="",
                    duration_ms=duration_ms,
                    success=False,
                    error=f"Hermes task timed out (agent: {agent_name})",
                )

            stdout, stderr = proc.communicate(timeout=5)
            duration_ms = int((time.time() - start_time) * 1000)

            if proc.returncode == 0:
                response = stdout.strip()
                tokens_in, tokens_out = _estimate_tokens(prompt, response)
                return TaskResult(
                    response=response,
                    duration_ms=duration_ms,
                    tokens_input=tokens_in,
                    tokens_output=tokens_out,
                    success=True,
                )
            else:
                error = stderr.strip() or f"exit code {proc.returncode}"
                return TaskResult(
                    response="",
                    duration_ms=duration_ms,
                    success=False,
                    error=error,
                )

        except FileNotFoundError:
            return TaskResult(
                response="",
                success=False,
                error=f"Hermes CLI '{self._hermes_bin}' not found",
            )

    def check_connectivity(self) -> bool:
        """Check hermes CLI is available and responds."""
        cmd = [self._hermes_bin, "--version"]
        sandbox_error = self._sandbox_check(cmd)
        if sandbox_error:
            return False
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def get_profile_info(self, profile: str = "sccsos") -> dict:
        """Profile information via `hermes profile show`."""
        cmd = [self._hermes_bin, "profile", "show", profile]
        sandbox_error = self._sandbox_check(cmd)
        if sandbox_error:
            return {"profile": profile, "error": f"Sandbox blocked: {sandbox_error}"}
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return {"profile": profile, "info": result.stdout.strip()}
            return {"profile": profile, "error": result.stderr.strip()}
        except FileNotFoundError:
            return {"profile": profile, "error": "hermes CLI not found"}


# ── Token Estimation ────────────────────────────────────────────────


def _estimate_tokens(prompt: str, response: str) -> tuple[int, int]:
    """Estimate token counts from prompt and response text.

    Uses a simple heuristic: ~4 chars per token for Chinese text,
    ~5 chars per token for English text. This is an approximation.
    """
    # Count Chinese characters
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', prompt + response))
    total_chars = len(prompt) + len(response)
    non_chinese = total_chars - chinese_chars

    # Chinese: ~1.5 chars/token, English: ~4 chars/token
    prompt_tokens = max(1, int(len(prompt) / 3.5))
    response_tokens = max(1, int(len(response) / 3.5))

    return prompt_tokens, response_tokens


# ── Mock Implementation ────────────────────────────────────────────


class MockHermesAdapter(HermesAdapter):
    """Mock Hermes adapter for testing."""

    def __init__(self):
        self.tasks: list[dict] = []
        self._connected = True

    def delegate_task(self, agent_name: str, prompt: str,
                      profile: str = "sccsos",
                      model: Optional[str] = None,
                      policy_engine=None,
                      cancel_event: threading.Event | None = None,
                      timeout: int = 300) -> TaskResult:
        # ── Policy pre-flight (same logic as subprocess adapter) ──
        if policy_engine is not None:
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

            # Tool access check — defense-in-depth (mirrors subprocess adapter)
            tool_result = policy_engine.check_tool_access(
                agent_name, "delegate_task"
            )
            if not tool_result.allowed:
                return TaskResult(
                    response="",
                    success=False,
                    error=f"Tool rejected: {tool_result.reason}",
                )

        self.tasks.append({
            "agent": agent_name,
            "prompt": prompt,
            "profile": profile,
            "model": model,
        })
        response = f"[mock] Task delegated to '{agent_name}' via '{profile}'"
        tokens_in, tokens_out = _estimate_tokens(prompt, response)
        return TaskResult(
            response=response,
            duration_ms=42,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            success=True,
        )

    def check_connectivity(self) -> bool:
        return self._connected

    def set_connected(self, value: bool) -> None:
        self._connected = value

    def get_profile_info(self, profile: str = "sccsos") -> dict:
        return {
            "profile": profile,
            "info": f"Mock profile: {profile}",
            "mock": True,
        }


# ── Factory ────────────────────────────────────────────────────────


def create_adapter(mode: str = "subprocess",
                   whitelist: Optional["CommandWhitelist"] = None,
                   hermes_bin: str = "hermes") -> HermesAdapter:
    """Create a Hermes adapter by mode name.

    Args:
        mode: ``\\"subprocess\\"`` (default) or ``\\"mock\\"``.
        whitelist: Optional CommandWhitelist for sandbox checks
            (only used by subprocess adapter).
        hermes_bin: Path to the Hermes CLI binary (default ``hermes``).
    """
    if mode == "mock":
        return MockHermesAdapter()
    elif mode == "subprocess":
        return HermesSubprocessAdapter(whitelist=whitelist, hermes_bin=hermes_bin)
    else:
        raise ValueError(f"Unknown adapter mode: {mode}")
