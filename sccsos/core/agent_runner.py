"""Agent Runner — manages running agent background processes.

Transforms ``agent start`` from a DB-only status update into a real
background process that stays alive and can receive prompts via
``agent ask``.

Architecture:
    AgentRuntime
      └─ AgentRunner
           ├─ AgentProcess "architect"  (background thread + task queue)
           ├─ AgentProcess "reviewer"   (background thread + task queue)
           └─ ...
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from sccsos.core.hermes_adapter import HermesAdapter, TaskResult

if TYPE_CHECKING:
    from sccsos.memory.memory_store import MemoryStore


@dataclass
class AskResult:
    """Result of an ``agent ask`` call."""
    response: str = ""
    success: bool = True
    error: str = ""


@dataclass
class _Task:
    """Internal task sent to an AgentProcess."""
    prompt: str
    result_queue: queue.Queue


class AgentProcess:
    """A single running agent in a background thread.

    The thread waits for tasks via an internal queue, executes them
    through the HermesAdapter, and puts the result back on the
    caller's result queue.

    Supports pause/resume: when paused, ask() returns an error
    immediately and the run loop skips processing new tasks.
    """

    def __init__(self, name: str, profile: str, adapter: HermesAdapter,
                 policy_engine=None, model: Optional[str] = None,
                 cancel_event: "threading.Event | None" = None,
                 memory_store: "MemoryStore | None" = None):
        self.name = name
        self.profile = profile
        self._adapter = adapter
        self._policy_engine = policy_engine
        self._model = model
        self._cancel_event = cancel_event
        self._memory_store = memory_store
        self._task_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._paused = threading.Event()  # Pause signal
        self._thread: Optional[threading.Thread] = None

    # ── Public API ───────────────────────────────────────────────

    def start(self) -> None:
        """Start the background thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._paused.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"agent-{self.name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the thread to stop and wait for it."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def pause(self) -> None:
        """Pause this agent — set paused flag. Running ask() will return error."""
        self._paused.set()

    def resume(self) -> None:
        """Resume this agent — clear paused flag."""
        self._paused.clear()

    def ask(self, prompt: str, timeout: float = 300.0) -> AskResult:
        """Send a prompt to this agent and wait for a response.

        Args:
            prompt: The prompt text to send.
            timeout: Max seconds to wait for a response.

        Returns:
            AskResult with the agent's response.
        """
        if self._paused.is_set():
            return AskResult(
                success=False,
                error=f"Agent '{self.name}' is paused. Use 'sccsos agent resume {self.name}' to resume.",
            )
        result_q: queue.Queue = queue.Queue()
        self._task_queue.put(_Task(prompt=prompt, result_queue=result_q))

        try:
            result = result_q.get(timeout=timeout)
            return result
        except queue.Empty:
            return AskResult(
                success=False,
                error=f"Agent '{self.name}' did not respond within {timeout}s",
            )

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    # ── Internal ─────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Main loop: wait for tasks or stop signal."""
        while not self._stop_event.is_set():
            # Check cancellation signal
            if self._cancel_event is not None and self._cancel_event.is_set():
                # Drain all pending tasks with cancellation error
                while not self._task_queue.empty():
                    try:
                        task = self._task_queue.get_nowait()
                        task.result_queue.put(AskResult(
                            success=False,
                            error=f"Agent '{self.name}' cancelled.",
                        ))
                    except queue.Empty:
                        break
                break  # Exit the loop
            try:
                task = self._task_queue.get(timeout=1.0)
            except queue.Empty:
                continue  # Check stop event again

            # If paused, drain the task with an error response
            if self._paused.is_set():
                task.result_queue.put(AskResult(
                    success=False,
                    error=f"Agent '{self.name}' is paused. Task discarded.",
                ))
                continue

            try:
                # Build prompt — inject memory context if available
                prompt = task.prompt
                if self._memory_store is not None:
                    memory_data = self._memory_store.get_all(self.name)
                    if memory_data:
                        ctx_lines = [f"  {k}: {v}" for k, v in memory_data.items()]
                        memory_context = "\n".join(ctx_lines)
                        prompt = (
                            f"[Persistent memory for {self.name}]\n"
                            f"{memory_context}\n\n"
                            f"---\n\n"
                            f"{task.prompt}"
                        )

                result = self._adapter.delegate_task(
                    agent_name=self.name,
                    prompt=prompt,
                    profile=self.profile,
                    model=self._model,
                    policy_engine=self._policy_engine,
                    cancel_event=self._cancel_event,
                )
                task.result_queue.put(AskResult(
                    response=result.response,
                    success=result.success,
                    error=result.error,
                ))
            except Exception as e:
                task.result_queue.put(AskResult(
                    success=False,
                    error=str(e),
                ))


class AgentRunner:
    """Manages running agent processes.

    Usage:
        runner = AgentRunner(adapter)
        runner.start_agent("architect", "sccsos")
        result = runner.ask_agent("architect", "Design a module")
        runner.stop_agent("architect")
    """

    def __init__(self, adapter: HermesAdapter, memory_store=None):
        self._adapter = adapter
        self._memory_store = memory_store
        self._processes: dict[str, AgentProcess] = {}
        self._lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────

    def start_agent(self, name: str, profile: str = "sccsos",
                     policy_engine=None, model: Optional[str] = None) -> bool:
        """Start an agent process in the background.

        Args:
            name: Agent name.
            profile: Hermes profile to use.
            policy_engine: Optional PolicyEngine for pre-flight checks.
            model: Optional model override.

        Returns:
            True if started, False if already running.
        """
        with self._lock:
            if name in self._processes and self._processes[name].is_alive:
                return False
            proc = AgentProcess(name, profile, self._adapter,
                                policy_engine=policy_engine, model=model,
                                memory_store=self._memory_store)
            proc.start()
            self._processes[name] = proc
            return True

    def stop_agent(self, name: str) -> bool:
        """Stop a running agent process.

        Args:
            name: Agent name.

        Returns:
            True if stopped, False if not running.
        """
        with self._lock:
            proc = self._processes.pop(name, None)
            if proc is None:
                return False
        proc.stop()
        return True

    def ask_agent(self, name: str, prompt: str,
                  timeout: float = 300.0) -> AskResult:
        """Send a prompt to a running agent.

        Args:
            name: Agent name (must be running and not paused).
            prompt: Prompt text.
            timeout: Max seconds to wait.

        Returns:
            AskResult with response or error.
        """
        proc = self._processes.get(name)
        if proc is None or not proc.is_alive:
            return AskResult(
                success=False,
                error=f"Agent '{name}' is not running. Use 'sccsos agent start {name}' first.",
            )
        if proc.is_paused:
            return AskResult(
                success=False,
                error=f"Agent '{name}' is paused. Use 'sccsos agent resume {name}' first.",
            )
        return proc.ask(prompt, timeout=timeout)

    def pause_agent(self, name: str) -> bool:
        """Pause a running agent.

        Args:
            name: Agent name.

        Returns:
            True if paused, False if not running.
        """
        proc = self._processes.get(name)
        if proc is None or not proc.is_alive:
            return False
        proc.pause()
        return True

    def resume_agent(self, name: str) -> bool:
        """Resume a paused agent.

        Args:
            name: Agent name.

        Returns:
            True if resumed, False if not running.
        """
        proc = self._processes.get(name)
        if proc is None or not proc.is_alive:
            return False
        proc.resume()
        return True

    def is_running(self, name: str) -> bool:
        """Check if an agent is currently running."""
        proc = self._processes.get(name)
        return proc is not None and proc.is_alive

    def is_paused(self, name: str) -> bool:
        """Check if an agent is currently paused."""
        proc = self._processes.get(name)
        return proc is not None and proc.is_paused

    def list_running(self) -> list[str]:
        """List names of currently running agents."""
        return [
            name for name, proc in self._processes.items()
            if proc.is_alive
        ]

    def stop_all(self, timeout: float = 5.0) -> int:
        """Stop all running agents.

        Args:
            timeout: Max seconds to wait per agent.

        Returns:
            Number of agents stopped.
        """
        with self._lock:
            names = list(self._processes.keys())
            for name in names:
                proc = self._processes.pop(name, None)
                if proc:
                    proc.stop(timeout=timeout)
        return len(names)

    @property
    def count(self) -> int:
        """Number of currently running agents."""
        return len(self.list_running())
