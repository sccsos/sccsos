"""Tests for RemoteHermesAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sccsos.core.hermes_remote_adapter import RemoteHermesAdapter
from sccsos.core.hermes_adapter import TaskResult


class TestRemoteHermesAdapter:
    """Unit tests for RemoteHermesAdapter."""

    def test_init_defaults(self):
        """Default constructor uses sensible values."""
        adapter = RemoteHermesAdapter()
        assert adapter._url == "http://localhost:8080"
        assert adapter._token == ""
        assert adapter._timeout == 60
        assert adapter._retry_count == 2
        assert adapter._delegate_endpoint == "http://localhost:8080/api/v1/delegate"

    def test_init_custom_url(self):
        """Custom URL is used, trailing slash stripped."""
        adapter = RemoteHermesAdapter(url="https://hermes-node.example.com:9090/")
        assert adapter._url == "https://hermes-node.example.com:9090"
        assert adapter._delegate_endpoint == (
            "https://hermes-node.example.com:9090/api/v1/delegate"
        )

    def test_init_with_token(self):
        """Token is stored for Authorization header."""
        adapter = RemoteHermesAdapter(url="http://localhost", token="secret123")
        assert adapter._token == "secret123"

    @patch("sccsos.core.hermes_remote_adapter.RemoteHermesAdapter._send_request")
    def test_delegate_task_success(self, mock_send):
        """Successful delegation returns TaskResult with response."""
        mock_send.return_value = TaskResult(
            response="Hello from remote agent",
            duration_ms=150,
            tokens_input=50,
            tokens_output=30,
            model="deepseek-v4-flash",
            cost_usd=0.001,
            success=True,
        )
        adapter = RemoteHermesAdapter(url="http://localhost:8080")
        result = adapter.delegate_task(
            agent_name="architect",
            prompt="设计一个认证模块",
        )
        assert result.success
        assert result.response == "Hello from remote agent"
        assert result.duration_ms == 150
        assert result.tokens_input == 50
        assert result.tokens_output == 30

    @patch("sccsos.core.hermes_remote_adapter.RemoteHermesAdapter._send_request")
    def test_delegate_task_http_error(self, mock_send):
        """HTTP error returns failure with status code."""
        mock_send.return_value = TaskResult(
            response="",
            success=False,
            error="HTTP 500: Internal Server Error",
        )
        adapter = RemoteHermesAdapter(url="http://localhost:8080")
        result = adapter.delegate_task(
            agent_name="architect",
            prompt="test",
        )
        assert not result.success
        assert "HTTP 500" in result.error

    @patch("sccsos.core.hermes_remote_adapter.RemoteHermesAdapter._send_request")
    def test_delegate_task_cancelled(self, mock_send):
        """Cancellation returns cancelled error immediately."""
        import threading
        cancel_event = threading.Event()
        cancel_event.set()

        adapter = RemoteHermesAdapter(url="http://localhost:8080")
        result = adapter.delegate_task(
            agent_name="architect",
            prompt="test",
            cancel_event=cancel_event,
        )
        assert not result.success
        assert "cancelled" in result.error.lower()

    @patch("sccsos.core.hermes_remote_adapter.RemoteHermesAdapter._send_request")
    def test_policy_preflight_blocks(self, mock_send):
        """Policy pre-flight blocks delegation when budget exceeded."""
        mock_policy = MagicMock()
        mock_policy.check_delegation.return_value = MagicMock(
            allowed=False, reason="Budget exceeded"
        )
        adapter = RemoteHermesAdapter(url="http://localhost:8080")
        result = adapter.delegate_task(
            agent_name="architect",
            prompt="test",
            policy_engine=mock_policy,
        )
        assert not result.success
        assert "Budget exceeded" in result.error
        # _send_request should NOT be called
        mock_send.assert_not_called()

    def test_connectivity_no_httpx(self):
        """check_connectivity returns False when httpx is not installed."""
        adapter = RemoteHermesAdapter(url="http://localhost:8080")
        with patch.dict("sys.modules", {"httpx": None}):
            # Force it to raise ImportError
            import sys
            orig = sys.modules.pop("httpx", None)
            try:
                assert not adapter.check_connectivity()
            finally:
                if orig:
                    sys.modules["httpx"] = orig

    @patch("sccsos.core.hermes_remote_adapter.RemoteHermesAdapter._send_request")
    def test_retry_on_transient_failure(self, mock_send):
        """Retries on transient failure, returns last error."""
        mock_send.side_effect = [
            TaskResult(response="", success=False, error="timeout attempt 1"),
            TaskResult(response="", success=False, error="timeout attempt 2"),
            TaskResult(response="", success=False, error="timeout attempt 3"),
        ]
        adapter = RemoteHermesAdapter(
            url="http://localhost:8080", retry_count=2,
        )
        result = adapter.delegate_task(
            agent_name="architect",
            prompt="test",
        )
        assert not result.success
        assert "attempt 3" in result.error
        assert mock_send.call_count == 3

    def test_get_profile_info_handles_import_error(self):
        """get_profile_info returns error dict when httpx missing."""
        adapter = RemoteHermesAdapter(url="http://localhost:8080")
        with patch.dict("sys.modules", {"httpx": None}):
            import sys
            orig = sys.modules.pop("httpx", None)
            try:
                result = adapter.get_profile_info("sccsos")
                assert "error" in result
                assert result["remote_url"] == "http://localhost:8080"
            finally:
                if orig:
                    sys.modules["httpx"] = orig
