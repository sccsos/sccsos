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


# ═══════════════════════════════════════════════════════════════════
# _send_request real HTTP path tests (mock httpx, not _send_request)
# ═══════════════════════════════════════════════════════════════════


class TestRemoteHermesAdapterSendRequest:
    """Test the actual _send_request HTTP code path."""

    @pytest.fixture
    def adapter(self):
        """Adapter without token for simpler tests."""
        return RemoteHermesAdapter(
            url="http://test-proxy:8080",
            token="",
            retry_count=0,
        )

    @patch("httpx.Client")
    def test_http_200_with_tokens(self, mock_client_class, adapter):
        """HTTP 200 with tokens returns success."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Hello from remote",
            "tokens_input": 50,
            "tokens_output": 30,
            "model": "gpt-4",
            "duration_ms": 200,
            "success": True,
            "cost_usd": 0.002,
        }
        mock_resp.elapsed.total_seconds.return_value = 0.2
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        result = adapter._send_request(
            {"agent_name": "architect", "prompt": "hello"},
            timeout=30, attempt=0,
        )
        assert result.success
        assert result.response == "Hello from remote"
        assert result.tokens_input == 50
        assert result.model == "gpt-4"

    @patch("httpx.Client")
    def test_http_200_without_tokens(self, mock_client_class, adapter):
        """HTTP 200 without tokens falls back to estimation."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 0.1
        mock_resp.json.return_value = {
            "response": "short reply",
            "success": True,
        }
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        result = adapter._send_request(
            {"agent_name": "architect", "prompt": "hello world"},
            timeout=30, attempt=0,
        )
        assert result.success
        # Tokens should be estimated since not in response
        assert result.tokens_input > 0

    @patch("httpx.Client")
    def test_http_400_error(self, mock_client_class, adapter):
        """HTTP 400 returns failure with status."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.elapsed.total_seconds.return_value = 0.05
        mock_resp.text = "Bad request: missing agent_name"
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        result = adapter._send_request(
            {"agent_name": "architect", "prompt": "test"},
            timeout=30, attempt=0,
        )
        assert not result.success
        assert "HTTP 400" in result.error
        assert "Bad request" in result.error

    @patch("httpx.Client")
    def test_http_500_error(self, mock_client_class, adapter):
        """HTTP 500 returns failure with error body."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.elapsed.total_seconds.return_value = 0.1
        mock_resp.text = "Internal Server Error"
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        result = adapter._send_request(
            {"agent_name": "architect", "prompt": "test"},
            timeout=30, attempt=0,
        )
        assert not result.success
        assert "HTTP 500" in result.error

    @patch("httpx.Client")
    def test_http_with_auth_token(self, mock_client_class):
        """Adapter with auth token sends Authorization header."""
        adapter = RemoteHermesAdapter(
            url="http://test-proxy:8080", token="my-secret",
            retry_count=0,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 0.1
        mock_resp.json.return_value = {"response": "ok", "success": True}
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        adapter._send_request(
            {"agent_name": "architect", "prompt": "hello"},
            timeout=30, attempt=0,
        )
        # Verify Authorization header was sent
        call_kwargs = mock_client.post.call_args.kwargs
        assert "Authorization" in call_kwargs.get("headers", {})
        assert call_kwargs["headers"]["Authorization"] == "Bearer my-secret"

    @patch("httpx.Client")
    def test_timeout_exception(self, mock_client_class, adapter):
        """httpx.TimeoutException is caught."""
        from httpx import TimeoutException
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = TimeoutException("timed out")
        mock_client_class.return_value = mock_client

        result = adapter._send_request(
            {"agent_name": "architect", "prompt": "test"},
            timeout=30, attempt=0,
        )
        assert not result.success
        assert "timeout" in result.error.lower()

    @patch("httpx.Client")
    def test_connect_error(self, mock_client_class, adapter):
        """httpx.ConnectError is caught."""
        from httpx import ConnectError
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = ConnectError("connection refused")
        mock_client_class.return_value = mock_client

        result = adapter._send_request(
            {"agent_name": "architect", "prompt": "test"},
            timeout=30, attempt=0,
        )
        assert not result.success
        assert "connect" in result.error.lower()

    @patch("httpx.Client")
    def test_generic_http_exception(self, mock_client_class, adapter):
        """Generic exception is caught."""
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = RuntimeError("unexpected error")
        mock_client_class.return_value = mock_client

        result = adapter._send_request(
            {"agent_name": "architect", "prompt": "test"},
            timeout=30, attempt=0,
        )
        assert not result.success
        assert "unexpected error" in result.error

    @patch("httpx.Client")
    def test_delegate_with_model_override(self, mock_client_class, adapter):
        """Model override is sent in payload."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 0.1
        mock_resp.json.return_value = {"response": "ok", "success": True}
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_class.return_value = mock_client

        adapter.delegate_task(
            agent_name="architect", prompt="test", model="gpt-4",
        )
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["json"]["model"] == "gpt-4"
