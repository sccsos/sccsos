"""Docker Hermes Adapter — Hermes CLI via docker exec.

Runs Hermes Agent CLI commands inside a Docker container,
enabling SCCS OS to use a containerized Hermes Agent without
requiring a local CLI installation.
"""

from __future__ import annotations

import shlex
import subprocess
import threading
import time
from typing import Optional

from sccsos.core.hermes_adapter import (
    HermesAdapter,
    TaskResult,
    _estimate_tokens,
)


class DockerHermesAdapter(HermesAdapter):
    """Hermes adapter that delegates via ``docker exec``.

    Usage::

        adapter = DockerHermesAdapter(container="hermes-agent")
        result = adapter.delegate_task(
            agent_name="architect",
            prompt="设计一个认证模块",
        )
    """

    def __init__(
        self,
        container: str = "hermes-agent",
        network: str = "host",
        retry_count: int = 2,
    ):
        self._container = container
        self._network = network
        self._retry_count = retry_count

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
        """Delegate via ``docker exec <container> hermes -p <profile> -z <prompt>``."""
        # Build docker exec command
        cmd = [
            "docker", "exec",
            self._container,
            "hermes", "-p", profile, "-z", prompt,
        ]
        if model:
            cmd.extend(["-m", model])

        # Run with retry
        start_time = time.time()
        last_error = ""
        for attempt in range(self._retry_count + 1):
            if cancel_event is not None and cancel_event.is_set():
                duration_ms = int((time.time() - start_time) * 1000)
                return TaskResult(
                    response="",
                    duration_ms=duration_ms,
                    success=False,
                    error=f"Task cancelled (agent: {agent_name})",
                )

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True, text=True,
                    timeout=timeout,
                )
                duration_ms = int((time.time() - start_time) * 1000)

                if result.returncode == 0:
                    response = result.stdout.strip()
                    tokens_in, tokens_out = _estimate_tokens(prompt, response)
                    return TaskResult(
                        response=response,
                        duration_ms=duration_ms,
                        tokens_input=tokens_in,
                        tokens_output=tokens_out,
                        success=True,
                    )
                else:
                    last_error = result.stderr.strip() or f"exit code {result.returncode}"

            except FileNotFoundError:
                return TaskResult(
                    response="",
                    success=False,
                    error="Docker CLI not found. Install Docker to use DockerHermesAdapter.",
                )
            except subprocess.TimeoutExpired:
                last_error = "Docker exec timed out"
            except Exception as e:
                last_error = str(e)

            if attempt < self._retry_count:
                time.sleep(min(2 ** attempt, 10))
                continue

        return TaskResult(
            response="",
            duration_ms=int((time.time() - start_time) * 1000),
            success=False,
            error=f"Docker Hermes task failed after {self._retry_count + 1} attempts: {last_error}",
        )

    def check_connectivity(self) -> bool:
        """Check if the Docker container is running and hermes CLI is available."""
        try:
            r = subprocess.run(
                ["docker", "exec", self._container, "hermes", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    def get_profile_info(self, profile: str = "sccsos") -> dict:
        """Get profile info from the container's Hermes."""
        try:
            r = subprocess.run(
                ["docker", "exec", self._container, "hermes", "config", "list-profiles"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                return {"profile": profile, "info": r.stdout.strip(), "container": self._container}
            return {"profile": profile, "error": r.stderr.strip(), "container": self._container}
        except Exception as e:
            return {"profile": profile, "error": str(e), "container": self._container}
