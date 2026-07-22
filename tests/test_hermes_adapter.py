"""Tests for HermesAdapter base — TaskResult, SubprocessAdapter, Mock, Factory."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from sccsos.core.hermes_adapter import (
    HermesAdapter,
    HermesSubprocessAdapter,
    MockHermesAdapter,
    TaskResult,
    _estimate_tokens,
    create_adapter,
)


# ═══════════════════════════════════════════════════════════════════
# TaskResult
# ═══════════════════════════════════════════════════════════════════


class TestTaskResult:
    """TaskResult dataclass behavior."""

    def test_default_values(self):
        """Default TaskResult has sensible defaults."""
        r = TaskResult(response="ok")
        assert r.response == "ok"
        assert r.success is True
        assert r.error == ""
        assert r.duration_ms == 0
        assert r.tokens_input == 0
        assert r.tokens_output == 0

    def test_failure_result(self):
        """Failure TaskResult can be created explicitly."""
        r = TaskResult(response="", success=False, error="timeout")
        assert not r.success
        assert r.error == "timeout"


# ═══════════════════════════════════════════════════════════════════
# _estimate_tokens
# ═══════════════════════════════════════════════════════════════════


class TestEstimateTokens:
    """Token estimation heuristics."""

    def test_english_text(self):
        """English text token estimation."""
        t_in, t_out = _estimate_tokens("hello world", "hi there")
        assert t_in > 0
        assert t_out > 0
        # Approximately 4 chars per token
        assert t_in == max(1, int(len("hello world") / 3.5))
        assert t_out == max(1, int(len("hi there") / 3.5))

    def test_chinese_text(self):
        """Chinese text token estimation (same heuristic applies across the board)."""
        t_in, t_out = _estimate_tokens("设计一个认证模块", "好的")
        assert t_in > 0
        assert t_out > 0

    def test_empty_response(self):
        """Empty response yields at least 1 token."""
        t_in, t_out = _estimate_tokens("test", "")
        assert t_in == 1
        assert t_out == 1

    def test_mixed_text(self):
        """Mixed Chinese/English estimation."""
        t_in, t_out = _estimate_tokens("设计 auth module", "return True")
        assert t_in > 0
        assert t_out > 0


# ═══════════════════════════════════════════════════════════════════
# HermesAdapter ABC
# ═══════════════════════════════════════════════════════════════════


class TestHermesAdapterABC:
    """HermesAdapter abstract interface cannot be instantiated directly."""

    def test_abstract_cannot_instantiate(self):
        """Cannot instantiate abstract HermesAdapter directly."""
        with pytest.raises(TypeError, match="abstract"):
            HermesAdapter()


# ═══════════════════════════════════════════════════════════════════
# MockHermesAdapter
# ═══════════════════════════════════════════════════════════════════


class TestMockHermesAdapter:
    """MockHermesAdapter used in testing."""

    def test_delegate_task_returns_mock_response(self):
        """Mock adapter returns predictable response."""
        adapter = MockHermesAdapter()
        result = adapter.delegate_task(
            agent_name="architect", prompt="design auth",
        )
        assert result.success
        assert "[mock]" in result.response
        assert "architect" in result.response
        assert result.duration_ms == 42

    def test_delegate_task_tracks_calls(self):
        """Mock adapter records delegated tasks."""
        adapter = MockHermesAdapter()
        adapter.delegate_task(agent_name="a1", prompt="hello")
        adapter.delegate_task(agent_name="a2", prompt="world")
        assert len(adapter.tasks) == 2
        assert adapter.tasks[0]["agent"] == "a1"
        assert adapter.tasks[1]["agent"] == "a2"

    def test_check_connectivity_default(self):
        """Default connectivity is True."""
        adapter = MockHermesAdapter()
        assert adapter.check_connectivity()

    def test_check_connectivity_set(self):
        """Connectivity can be toggled."""
        adapter = MockHermesAdapter()
        adapter.set_connected(False)
        assert not adapter.check_connectivity()

    def test_get_profile_info(self):
        """Profile info returns mock info."""
        adapter = MockHermesAdapter()
        info = adapter.get_profile_info("sccsos")
        assert info["profile"] == "sccsos"
        assert info["mock"] is True

    def test_delegate_task_with_model(self):
        """Model override is tracked."""
        adapter = MockHermesAdapter()
        adapter.delegate_task(
            agent_name="a1", prompt="hello", model="gpt-4",
        )
        assert adapter.tasks[0]["model"] == "gpt-4"

    def test_delegate_task_with_profile(self):
        """Profile override is tracked."""
        adapter = MockHermesAdapter()
        adapter.delegate_task(
            agent_name="a1", prompt="hello", profile="custom",
        )
        assert adapter.tasks[0]["profile"] == "custom"

    def test_policy_engine_rejects(self):
        """Policy engine pre-flight can reject delegation."""
        mock_policy = MagicMock()
        mock_policy.check_delegation.return_value = MagicMock(
            allowed=False, reason="Budget exceeded",
        )
        adapter = MockHermesAdapter()
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
            policy_engine=mock_policy,
        )
        assert not result.success
        assert "Budget exceeded" in result.error

    def test_policy_engine_tool_access_rejects(self):
        """Tool access check can also reject (defense-in-depth)."""
        mock_policy = MagicMock()
        mock_policy.check_delegation.return_value = MagicMock(
            allowed=True, reason="",
        )
        mock_policy.check_tool_access.return_value = MagicMock(
            allowed=False, reason="delegate_task not in whitelist",
        )
        adapter = MockHermesAdapter()
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
            policy_engine=mock_policy,
        )
        assert not result.success
        assert "delegate_task" in result.error


# ═══════════════════════════════════════════════════════════════════
# HermesSubprocessAdapter
# ═══════════════════════════════════════════════════════════════════


class TestHermesSubprocessAdapter:
    """Subprocess-based adapter tests."""

    def test_init_defaults(self):
        """Default constructor."""
        adapter = HermesSubprocessAdapter()
        assert adapter._hermes_bin == "hermes"
        assert adapter._whitelist is None
        assert adapter._retry_count == 2

    def test_init_with_whitelist(self):
        """Whitelist is stored for sandbox checks."""
        whitelist = MagicMock()
        adapter = HermesSubprocessAdapter(whitelist=whitelist)
        assert adapter._whitelist is whitelist

    def test_sandbox_check_no_whitelist(self):
        """Without whitelist, sandbox check returns None (allowed)."""
        adapter = HermesSubprocessAdapter()
        assert adapter._sandbox_check(["hermes", "-z", "test"]) is None

    def test_sandbox_check_blocked(self):
        """With whitelist, blocked command returns reason."""
        whitelist = MagicMock()
        whitelist.check.return_value = MagicMock(allowed=False, reason="blocked")
        adapter = HermesSubprocessAdapter(whitelist=whitelist)
        result = adapter._sandbox_check(["hermes", "-z", "rm -rf /"])
        assert result == "blocked"

    def test_sandbox_check_allowed(self):
        """With whitelist, allowed command returns None."""
        whitelist = MagicMock()
        whitelist.check.return_value = MagicMock(allowed=True)
        adapter = HermesSubprocessAdapter(whitelist=whitelist)
        assert adapter._sandbox_check(["hermes", "-z", "ls"]) is None

    @patch("sccsos.core.hermes_adapter.HermesSubprocessAdapter._run_single_attempt")
    def test_delegate_task_success(self, mock_run):
        """Successful delegation returns TaskResult."""
        mock_run.return_value = TaskResult(
            response="hello", success=True,
        )
        adapter = HermesSubprocessAdapter()
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
        )
        assert result.success
        assert result.response == "hello"

    @patch("sccsos.core.hermes_adapter.HermesSubprocessAdapter._run_single_attempt")
    def test_delegate_task_with_model(self, mock_run):
        """Model override is passed as -m argument."""
        mock_run.return_value = TaskResult(response="ok", success=True)
        adapter = HermesSubprocessAdapter()
        result = adapter.delegate_task(
            agent_name="architect", prompt="test", model="gpt-4",
        )
        # Verify the command included -m gpt-4 via _run_single_attempt
        call_args = mock_run.call_args[0][0]
        assert "-m" in call_args
        assert "gpt-4" in call_args

    @patch("sccsos.core.hermes_adapter.subprocess.Popen")
    def test_run_single_attempt_success(self, mock_popen):
        """_run_single_attempt returns success when process exits 0."""
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.returncode = 0
        proc.communicate.return_value = ("hello", "")
        mock_popen.return_value = proc

        adapter = HermesSubprocessAdapter()
        with patch("sccsos.core.hermes_adapter.time.time") as mock_time:
            # start_time=0, timeout=300, deadline=300
            # time.time() < 300 → True → poll returns 0 → break
            mock_time.return_value = 100.0
            result = adapter._run_single_attempt(
                ["hermes", "-z", "test"], "architect",
                None, 0.0, 300, prompt="test",
            )
        assert result.success
        assert result.response == "hello"

    @patch("sccsos.core.hermes_adapter.subprocess.Popen")
    def test_run_single_attempt_timeout(self, mock_popen):
        """_run_single_attempt returns timeout error when deadline reached."""
        proc = MagicMock()
        # Never finish polling
        proc.poll.return_value = None
        mock_popen.return_value = proc

        adapter = HermesSubprocessAdapter()
        with patch("sccsos.core.hermes_adapter.time.time") as mock_time:
            # start_time=0, timeout=1, deadline=1
            # 1st: 0.0 < 1 → enter loop → poll=None → sleep → 2nd: 0.5 < 1 → poll=None
            # → 3rd: 2.0 NOT < 1 → timeout path
            mock_time.side_effect = [0.0, 0.5, 2.0, 2.5]
            result = adapter._run_single_attempt(
                ["hermes", "-z", "test"], "architect",
                None, 0.0, 1, prompt="test",
            )
        assert not result.success
        assert "timed out" in result.error

    @patch("sccsos.core.hermes_adapter.subprocess.Popen")
    def test_run_single_attempt_cancelled(self, mock_popen):
        """_run_single_attempt returns cancel when event set during poll."""
        proc = MagicMock()
        proc.poll.return_value = None
        mock_popen.return_value = proc

        cancel_event = threading.Event()

        adapter = HermesSubprocessAdapter()
        with patch("sccsos.core.hermes_adapter.time.time") as mock_time:
            mock_time.side_effect = [0.0, 0.5]
            # Set cancel event during polling
            cancel_event.set()
            result = adapter._run_single_attempt(
                ["hermes", "-z", "test"], "architect",
                cancel_event, 0.0, 300, prompt="test",
            )
        assert not result.success
        assert "cancelled" in result.error

    @patch("sccsos.core.hermes_adapter.subprocess.Popen")
    def test_run_single_attempt_file_not_found(self, mock_popen):
        """_run_single_attempt returns FileNotFound error."""
        mock_popen.side_effect = FileNotFoundError()
        adapter = HermesSubprocessAdapter()
        result = adapter._run_single_attempt(
            ["hermes"], "architect", None, 0.0, 300, prompt="test",
        )
        assert not result.success
        assert "not found" in result.error

    @patch("sccsos.core.hermes_adapter.HermesSubprocessAdapter._run_single_attempt")
    def test_retry_on_transient_failure(self, mock_run):
        """Retry on transient failures, then succeed."""
        mock_run.side_effect = [
            TaskResult(response="", success=False, error="attempt 1"),
            TaskResult(response="done", success=True),
        ]
        adapter = HermesSubprocessAdapter(retry_count=1)
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
        )
        assert result.success
        assert mock_run.call_count == 2

    @patch("sccsos.core.hermes_adapter.HermesSubprocessAdapter._run_single_attempt")
    def test_policy_preflight_blocks(self, mock_run):
        """Policy pre-flight blocks delegation early."""
        mock_policy = MagicMock()
        mock_policy.check_delegation.return_value = MagicMock(
            allowed=False, reason="Daily budget exceeded",
        )
        adapter = HermesSubprocessAdapter()
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
            policy_engine=mock_policy,
        )
        assert not result.success
        assert "Daily budget" in result.error
        # _run_single_attempt should NOT be called
        mock_run.assert_not_called()

    @patch("sccsos.core.hermes_adapter.HermesSubprocessAdapter._run_single_attempt")
    def test_sandbox_blocks(self, mock_run):
        """Sandbox pre-flight blocks delegation early."""
        whitelist = MagicMock()
        whitelist.check.return_value = MagicMock(allowed=False, reason="rm -rf blocked")
        adapter = HermesSubprocessAdapter(whitelist=whitelist)
        result = adapter.delegate_task(
            agent_name="architect", prompt="rm -rf /",
        )
        assert not result.success
        assert "rm -rf blocked" in result.error
        mock_run.assert_not_called()

    def test_check_connectivity_sandbox_blocked(self):
        """check_connectivity returns False when sandbox blocks."""
        whitelist = MagicMock()
        whitelist.check.return_value = MagicMock(allowed=False, reason="blocked")
        adapter = HermesSubprocessAdapter(whitelist=whitelist)
        assert not adapter.check_connectivity()

    @patch("sccsos.core.hermes_adapter.subprocess.run")
    def test_check_connectivity_success(self, mock_run):
        """check_connectivity returns True on success."""
        mock_run.return_value = MagicMock(returncode=0)
        adapter = HermesSubprocessAdapter()
        assert adapter.check_connectivity()

    @patch("sccsos.core.hermes_adapter.subprocess.run")
    def test_get_profile_info_sandbox_blocked(self, mock_run):
        """get_profile_info returns error when sandbox blocks."""
        whitelist = MagicMock()
        whitelist.check.return_value = MagicMock(allowed=False, reason="blocked")
        adapter = HermesSubprocessAdapter(whitelist=whitelist)
        result = adapter.get_profile_info("sccsos")
        assert "error" in result
        assert "blocked" in result["error"]

    @patch("sccsos.core.hermes_adapter.subprocess.run")
    def test_get_profile_info_success(self, mock_run):
        """get_profile_info returns info on success."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="profile: sccsos", stderr="",
        )
        adapter = HermesSubprocessAdapter()
        result = adapter.get_profile_info("sccsos")
        assert result["profile"] == "sccsos"
        assert result["info"] == "profile: sccsos"

    def test_get_profile_info_file_not_found(self):
        """get_profile_info returns error when hermes CLI not found."""
        adapter = HermesSubprocessAdapter(hermes_bin="nonexistent-hermes")
        with patch("sccsos.core.hermes_adapter.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = adapter.get_profile_info("sccsos")
            assert "error" in result
            assert "not found" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# create_adapter factory
# ═══════════════════════════════════════════════════════════════════


class TestCreateAdapter:
    """Factory function tests."""

    def test_mock_mode(self):
        """mode='mock' returns MockHermesAdapter."""
        adapter = create_adapter(mode="mock")
        assert isinstance(adapter, MockHermesAdapter)

    def test_subprocess_mode(self):
        """mode='subprocess' returns HermesSubprocessAdapter."""
        adapter = create_adapter(mode="subprocess")
        assert isinstance(adapter, HermesSubprocessAdapter)

    def test_unknown_mode(self):
        """Unknown mode raises ValueError."""
        with pytest.raises(ValueError, match="Unknown adapter mode"):
            create_adapter(mode="invalid")
