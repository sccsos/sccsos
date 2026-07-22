"""Tests for DockerHermesAdapter — Hermes CLI via docker exec."""

from __future__ import annotations

import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest

from sccsos.core.hermes_docker_adapter import DockerHermesAdapter
from sccsos.core.hermes_adapter import TaskResult


class TestDockerHermesAdapterInit:
    """Constructor tests."""

    def test_init_defaults(self):
        """Default constructor uses sensible values."""
        adapter = DockerHermesAdapter()
        assert adapter._container == "hermes-agent"
        assert adapter._network == "host"
        assert adapter._retry_count == 2

    def test_init_custom(self):
        """Custom container and retry count."""
        adapter = DockerHermesAdapter(
            container="my-agent", network="bridge", retry_count=3,
        )
        assert adapter._container == "my-agent"
        assert adapter._network == "bridge"
        assert adapter._retry_count == 3


class TestDockerHermesAdapterDelegate:
    """delegate_task method tests with mocked subprocess."""

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_success(self, mock_run):
        """Successful docker exec returns TaskResult with response."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Hello from container", stderr="",
        )
        adapter = DockerHermesAdapter()
        result = adapter.delegate_task(
            agent_name="architect", prompt="design auth",
        )
        assert result.success
        assert result.response == "Hello from container"
        assert result.tokens_input > 0
        assert result.tokens_output > 0

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_success_with_model(self, mock_run):
        """Model override is passed as -m argument."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="With model", stderr="",
        )
        adapter = DockerHermesAdapter()
        result = adapter.delegate_task(
            agent_name="architect", prompt="test", model="gpt-4",
        )
        assert result.success
        # Verify the command included -m gpt-4
        call_args = mock_run.call_args[0][0]
        assert "-m" in call_args
        assert "gpt-4" in call_args

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_non_zero_exit(self, mock_run):
        """Non-zero exit code returns failure with stderr."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="permission denied",
        )
        adapter = DockerHermesAdapter(retry_count=0)
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
        )
        assert not result.success
        assert "permission denied" in result.error

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_cancel_before_attempt(self, mock_run):
        """Cancel event set before execution returns cancelled immediately."""
        cancel_event = threading.Event()
        cancel_event.set()
        adapter = DockerHermesAdapter()
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
            cancel_event=cancel_event,
        )
        assert not result.success
        assert "cancelled" in result.error.lower()

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_file_not_found(self, mock_run):
        """Docker CLI not found returns appropriate error."""
        mock_run.side_effect = FileNotFoundError()
        adapter = DockerHermesAdapter(retry_count=0)
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
        )
        assert not result.success
        assert "Docker CLI not found" in result.error

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_timeout_expired(self, mock_run):
        """Subprocess.TimeoutExpired triggers retry then failure."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=10)
        adapter = DockerHermesAdapter(retry_count=1)
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
        )
        assert not result.success
        assert "timed out" in result.error.lower()
        # Should have retried
        assert mock_run.call_count == 2

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_retry_then_success(self, mock_run):
        """Retry after transient failure then succeed."""
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd="docker", timeout=10),
            MagicMock(
                returncode=0, stdout="Recovered!", stderr="",
            ),
        ]
        adapter = DockerHermesAdapter(retry_count=1)
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
        )
        assert result.success
        assert result.response == "Recovered!"
        assert mock_run.call_count == 2

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_generic_exception(self, mock_run):
        """Generic exception is caught and included in error."""
        mock_run.side_effect = RuntimeError("unexpected error")
        adapter = DockerHermesAdapter(retry_count=0)
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
        )
        assert not result.success
        assert "unexpected error" in result.error

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_all_retries_exhausted(self, mock_run):
        """All retry attempts exhausted returns aggregated failure."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=10)
        adapter = DockerHermesAdapter(retry_count=2)
        result = adapter.delegate_task(
            agent_name="architect", prompt="test",
        )
        assert not result.success
        assert "failed after 3 attempts" in result.error


class TestDockerHermesAdapterConnectivity:
    """check_connectivity and get_profile_info tests."""

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_connectivity_success(self, mock_run):
        """check_connectivity returns True when docker exec works."""
        mock_run.return_value = MagicMock(returncode=0)
        adapter = DockerHermesAdapter()
        assert adapter.check_connectivity()

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_connectivity_failure(self, mock_run):
        """check_connectivity returns False when docker exec fails."""
        mock_run.return_value = MagicMock(returncode=1)
        adapter = DockerHermesAdapter()
        assert not adapter.check_connectivity()

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_connectivity_exception(self, mock_run):
        """check_connectivity returns False on exception."""
        mock_run.side_effect = FileNotFoundError()
        adapter = DockerHermesAdapter()
        assert not adapter.check_connectivity()

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_get_profile_info_success(self, mock_run):
        """get_profile_info returns profile info on success."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="sccsos\ndefault", stderr="",
        )
        adapter = DockerHermesAdapter()
        result = adapter.get_profile_info("sccsos")
        assert result["profile"] == "sccsos"
        assert "info" in result
        assert "sccsos" in result["info"]

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_get_profile_info_stderr(self, mock_run):
        """get_profile_info returns error from stderr on failure."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="container not found",
        )
        adapter = DockerHermesAdapter()
        result = adapter.get_profile_info("sccsos")
        assert "error" in result
        assert "container not found" in result["error"]

    @patch("sccsos.core.hermes_docker_adapter.subprocess.run")
    def test_get_profile_info_exception(self, mock_run):
        """get_profile_info returns error dict on exception."""
        mock_run.side_effect = RuntimeError("docker daemon down")
        adapter = DockerHermesAdapter()
        result = adapter.get_profile_info("sccsos")
        assert "error" in result
        assert "docker daemon down" in result["error"]
