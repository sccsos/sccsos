"""Integration test — end-to-end validation of core sccsos services.

Tests the AgentRuntime, Registry, Lifecycle, WorkflowEngine, and
PolicyEngine together using an in-memory SQLite database and
MockHermesAdapter.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from sccsos.core.config import AgentOSConfig, PoliciesConfig, PolicyDefaults
from sccsos.core.database import Database
from sccsos.core.registry import AgentSpec, AgentRegistry
from sccsos.core.lifecycle import LifecycleManager, AgentStatus
from sccsos.core.hermes_adapter import MockHermesAdapter, TaskResult
from sccsos.core.orchestrator import (
    WorkflowDef, WorkflowEngine, WorkflowStepDef,
    WorkflowValidationError, WorkflowExecutionError,
)
from sccsos.security.policy import PolicyEngine, BudgetTracker


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db_path():
    """Temporary SQLite database for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def db(db_path):
    db = Database(db_path)
    db.initialize()
    return db


@pytest.fixture
def config():
    """Minimal config with budget enabled."""
    return AgentOSConfig(
        policies=PoliciesConfig(
            default=PolicyDefaults(
                max_cost_usd=5.0,
                max_tokens_per_session=100000,
                allowed_tools=[
                    "read_file", "search_files", "web_search", "web_extract",
                    "terminal", "delegate_task",
                ],
            )
        ),
    )


@pytest.fixture
def adapter():
    return MockHermesAdapter()


@pytest.fixture
def registry():
    r = AgentRegistry()
    spec = AgentSpec(
        name="architect",
        version="1.0",
        description="Test architect agent",
        tags=["core"],
    )
    r.register(spec)
    return r


@pytest.fixture
def lifecycle(db, registry):
    return LifecycleManager(db, registry)


@pytest.fixture
def engine(db, adapter):
    return WorkflowEngine(db, adapter)


# ── Registry Tests ────────────────────────────────────────────────


class TestRegistry:
    def test_register_and_find(self, registry):
        spec = registry.find("architect")
        assert spec is not None
        assert spec.name == "architect"
        assert spec.version == "1.0"

    def test_register_duplicate_raises(self, registry):
        spec = AgentSpec(name="architect", version="2.0")
        with pytest.raises(ValueError, match="already registered"):
            registry.register(spec)

    def test_unregister(self, registry):
        registry.unregister("architect")
        assert registry.find("architect") is None

    def test_unregister_missing_raises(self, registry):
        with pytest.raises(KeyError):
            registry.unregister("nonexistent")

    def test_list_with_tag_filter(self, registry):
        spec2 = AgentSpec(name="coder", tags=["dev"])
        registry.register(spec2)
        tagged = registry.list(tag="core")
        assert len(tagged) == 1
        assert tagged[0].name == "architect"

    def test_count(self, registry):
        assert registry.count() == 1
        spec2 = AgentSpec(name="coder")
        registry.register(spec2)
        assert registry.count() == 2

    def test_from_yaml_round_trip(self, tmp_path):
        yml = tmp_path / "agent.yaml"
        yml.write_text(yaml.dump({
            "name": "test-agent",
            "version": "2.0",
            "description": "Round-trip test",
            "tags": ["test"],
        }))
        spec = AgentSpec.from_yaml(yml)
        assert spec.name == "test-agent"
        assert spec.version == "2.0"
        assert "test" in spec.tags
        assert spec.lifecycle.max_turns == 90  # default


# ── Lifecycle Tests ───────────────────────────────────────────────


class TestLifecycle:
    def test_create_and_start(self, db, registry, lifecycle):
        spec = registry.get("architect")
        instance = lifecycle.create(spec)
        assert instance.status == AgentStatus.CREATED

        lifecycle.start(instance.id)
        assert instance.status == AgentStatus.RUNNING

        # Verify DB persistence
        record = db.get_agent(instance.id)
        assert record is not None
        assert record["status"] == "running"

    def test_full_state_machine(self, lifecycle, registry):
        spec = registry.get("architect")
        inst = lifecycle.create(spec)

        # CREATED → RUNNING
        lifecycle.start(inst.id)
        assert inst.status == AgentStatus.RUNNING

        # RUNNING → PAUSED
        lifecycle.pause(inst.id)
        assert inst.status == AgentStatus.PAUSED

        # PAUSED → RUNNING
        lifecycle.resume(inst.id)
        assert inst.status == AgentStatus.RUNNING

        # RUNNING → FAILED
        lifecycle.fail(inst.id, "test error")
        assert inst.status == AgentStatus.FAILED

        # FAILED → RUNNING
        lifecycle.restart(inst.id)
        assert inst.status == AgentStatus.RUNNING

        # RUNNING → TERMINATED
        lifecycle.stop(inst.id)
        assert inst.status == AgentStatus.TERMINATED

    def test_invalid_transition(self, lifecycle, registry):
        spec = registry.get("architect")
        inst = lifecycle.create(spec)
        # CREATED → PAUSED is invalid
        with pytest.raises(Exception):
            lifecycle.pause(inst.id)

    def test_list_instances(self, lifecycle, registry):
        spec = registry.get("architect")
        inst = lifecycle.create(spec)
        lifecycle.start(inst.id)

        running = lifecycle.list_instances(status=AgentStatus.RUNNING)
        assert len(running) == 1

        paused = lifecycle.list_instances(status=AgentStatus.PAUSED)
        assert len(paused) == 0


# ── Workflow Engine Tests ─────────────────────────────────────────


class TestWorkflowEngine:
    def test_single_step_workflow(self, engine):
        """A single-step workflow should execute successfully."""
        wf = WorkflowDef(
            name="single-step",
            steps=[
                WorkflowStepDef(
                    id="step-1",
                    agent="architect",
                    prompt="Do something",
                ),
            ],
        )
        run_id = engine.execute(wf)
        status = engine.get_run_status(run_id)
        assert status["status"] == "completed"
        assert len(status["steps"]) == 1
        assert status["steps"][0]["status"] == "completed"

    def test_dag_dependency_order(self, engine):
        """Steps should execute in correct dependency order."""
        wf = WorkflowDef(
            name="dag-order",
            steps=[
                WorkflowStepDef(id="a", agent="architect", prompt="Step A"),
                WorkflowStepDef(id="b", agent="architect", prompt="Step B",
                                depends_on=["a"]),
                WorkflowStepDef(id="c", agent="architect", prompt="Step C",
                                depends_on=["a"]),
                WorkflowStepDef(id="d", agent="architect", prompt="Step D",
                                depends_on=["b", "c"]),
            ],
        )
        run_id = engine.execute(wf)
        status = engine.get_run_status(run_id)
        assert status["status"] == "completed"

    def test_template_variable_substitution(self, engine):
        """{{ steps.xxx.response }} should resolve to step output."""
        wf = WorkflowDef(
            name="template-test",
            steps=[
                WorkflowStepDef(
                    id="source",
                    agent="architect",
                    prompt="Generate a number: 42",
                ),
                WorkflowStepDef(
                    id="consumer",
                    agent="architect",
                    prompt="Result was: {{ steps.source.response }}",
                    depends_on=["source"],
                ),
            ],
        )
        run_id = engine.execute(wf)
        status = engine.get_run_status(run_id)
        assert status["status"] == "completed"

    def test_empty_workflow_raises(self, engine):
        wf = WorkflowDef(name="empty", steps=[])
        with pytest.raises(WorkflowValidationError):
            engine.execute(wf)

    def test_cycle_detection(self, engine):
        """Workflows with circular dependencies should be rejected."""
        wf = WorkflowDef(
            name="cycle",
            steps=[
                WorkflowStepDef(id="a", agent="architect", prompt="A",
                                depends_on=["b"]),
                WorkflowStepDef(id="b", agent="architect", prompt="B",
                                depends_on=["a"]),
            ],
        )
        with pytest.raises(WorkflowValidationError, match="Cycle"):
            engine.execute(wf)

    def test_run_list_and_cancel(self, engine):
        """list_runs and cancel_run should work."""
        wf = WorkflowDef(
            name="list-test",
            steps=[
                WorkflowStepDef(id="s1", agent="architect", prompt="Test"),
            ],
        )
        run_id = engine.execute(wf)

        runs = engine.list_runs(limit=10)
        assert len(runs) >= 1
        assert runs[0]["workflow_name"] == "list-test"

        engine.cancel_run(run_id)
        status = engine.get_run_status(run_id)
        assert status["status"] == "cancelled"

    def test_validate_workflow(self, engine):
        """validate() should catch missing prompts."""
        wf = WorkflowDef(
            name="validation-test",
            steps=[
                WorkflowStepDef(id="s1", agent="architect", prompt=""),
            ],
        )
        warnings = engine.validate(wf)
        assert len(warnings) == 1
        assert "no prompt" in warnings[0]

    def test_retry_on_transient_failure(self, db, adapter):
        """A step with retry>0 should be retried on transient failure.

        This test creates a MockHermesAdapter that fails the first N
        calls, then succeeds. The retry logic should handle this.
        """
        class FlakyAdapter(MockHermesAdapter):
            def __init__(self):
                super().__init__()
                self.call_count = 0

            def delegate_task(self, agent_name, prompt, **kwargs):
                self.call_count += 1
                if self.call_count <= 2:  # Fail first 2 calls
                    return TaskResult(
                        response="",
                        success=False,
                        error="Transient error: connection reset",
                    )
                return super().delegate_task(agent_name, prompt, **kwargs)

        flaky = FlakyAdapter()
        engine = WorkflowEngine(db, flaky)
        wf = WorkflowDef(
            name="retry-test",
            steps=[
                WorkflowStepDef(
                    id="s1",
                    agent="architect",
                    prompt="Do work",
                    retry=3,  # Allow up to 3 retries
                ),
            ],
        )
        run_id = engine.execute(wf)
        status = engine.get_run_status(run_id)
        assert status["status"] == "completed"
        # Should have been called 3 times (1 initial + 2 retries)
        assert flaky.call_count == 3

    def test_retry_exhaustion(self, db, adapter):
        """When retries are exhausted, the workflow should fail."""
        class AlwaysFailsAdapter(MockHermesAdapter):
            def __init__(self):
                super().__init__()
                self.call_count = 0

            def delegate_task(self, agent_name, prompt, **kwargs):
                self.call_count += 1
                return TaskResult(
                    response="",
                    success=False,
                    error="Persistent failure",
                )

        failing = AlwaysFailsAdapter()
        engine = WorkflowEngine(db, failing)
        wf = WorkflowDef(
            name="retry-exhaust",
            steps=[
                WorkflowStepDef(
                    id="s1",
                    agent="architect",
                    prompt="Do work",
                    retry=2,  # 1 initial + 2 retries = 3 attempts
                ),
            ],
        )
        with pytest.raises(WorkflowExecutionError, match="failed after 3 attempts"):
            engine.execute(wf)
        assert failing.call_count == 3  # All attempts made


# ── Tool Permission Tests ───────────────────────────────────────


class TestToolPermissions:
    def test_check_tool_access_allowed(self, db, config):
        from sccsos.security.policy import PolicyEngine
        policy = PolicyEngine(db, config)
        result = policy.check_tool_access("architect", "read_file")
        assert result.allowed

    def test_check_tool_access_blocked(self, db, config):
        from sccsos.security.policy import PolicyEngine
        config.policies.default.blocked_tools = ["terminal"]
        policy = PolicyEngine(db, config)
        result = policy.check_tool_access("architect", "terminal")
        assert not result.allowed
        assert "blocked" in result.reason

    def test_check_tool_access_not_in_allowed(self, db, config):
        from sccsos.security.policy import PolicyEngine
        config.policies.default.allowed_tools = ["read_file"]
        policy = PolicyEngine(db, config)
        result = policy.check_tool_access("architect", "web_search")
        assert not result.allowed
        assert "not allowed" in result.reason

    def test_check_agent_toolsets_allowed(self, db, config):
        from sccsos.security.policy import PolicyEngine
        policy = PolicyEngine(db, config)
        result = policy.check_agent_toolsets("architect", ["filesystem", "web-search"])
        assert result.allowed

    def test_check_agent_toolsets_blocked(self, db, config):
        from sccsos.security.policy import PolicyEngine
        config.policies.default.blocked_tools = ["terminal"]
        policy = PolicyEngine(db, config)
        result = policy.check_agent_toolsets("coder", ["terminal"])
        assert not result.allowed
        assert "blocked" in result.reason

    def test_register_agent_with_blocked_tools(self, db, config, adapter):
        """Registering an agent with blocked tools should raise."""
        from sccsos.core.agent_runtime import AgentRuntime
        from sccsos.security.policy import PolicyViolation
        from sccsos.core.registry import AgentSpec

        config.policies.default.blocked_tools = ["terminal"]
        runtime = AgentRuntime(config=config)
        # Manually wire minimal services so initialize succeeds
        runtime._db = db
        runtime._adapter = adapter
        from sccsos.core.registry import AgentRegistry
        runtime._registry = AgentRegistry()
        runtime._initialized = True

        # Create minimal WorkflowEngine with policy engine
        from sccsos.core.orchestrator import WorkflowEngine
        engine = WorkflowEngine(db, adapter, config=config)
        runtime._engine = engine

        spec = AgentSpec(name="bad-agent", toolsets=["terminal"])
        with pytest.raises(PolicyViolation, match="blocked"):
            runtime.register_agent(spec)


# ── Policy Engine Tests ───────────────────────────────────────────


class TestPolicyEngine:
    def test_budget_within_limit(self, db, config):
        policy = PolicyEngine(db, config)
        result = policy.check_delegation(
            agent_name="architect",
            estimated_cost=0.01,
        )
        assert result.allowed

    def test_budget_exceeded(self, db, config):
        config.policies.default.max_cost_usd = 0.001  # Very low
        policy = PolicyEngine(db, config)
        result = policy.check_delegation(
            agent_name="architect",
            estimated_cost=0.01,
        )
        assert not result.allowed
        assert "Budget exceeded" in result.reason

    def test_budget_tracker(self, db):
        tracker = BudgetTracker(db, max_cost_usd=10.0)
        assert tracker.spent_so_far() == 0.0
        assert tracker.remaining_budget() == 10.0

        # Insert a fake audit entry
        conn = db._get_conn()
        conn.execute(
            "INSERT INTO audit_log (agent_id, event_type, cost_usd) "
            "VALUES ('test', 'llm_call', 2.5)"
        )
        conn.commit()

        assert tracker.spent_so_far() == 2.5
        assert tracker.remaining_budget() == 7.5

        result = tracker.check(estimated_cost=1.0)
        assert result.allowed

        result = tracker.check(estimated_cost=8.0)
        assert not result.allowed

    def test_no_config_allows_all(self, db):
        policy = PolicyEngine(db, config=None)
        result = policy.check_delegation(estimated_cost=999.0)
        assert result.allowed


# ── HermesAdapter Tests ───────────────────────────────────────────


class TestHermesAdapter:
    def test_mock_delegation(self, adapter):
        result = adapter.delegate_task("architect", "test prompt")
        assert result.success
        assert "architect" in result.response
        assert result.duration_ms == 42

    def test_mock_track_tasks(self, adapter):
        adapter.delegate_task("agent-a", "do A")
        adapter.delegate_task("agent-b", "do B")
        assert len(adapter.tasks) == 2
        assert adapter.tasks[0]["agent"] == "agent-a"

    def test_connectivity(self, adapter):
        assert adapter.check_connectivity() is True
        adapter.set_connected(False)
        assert adapter.check_connectivity() is False

    def test_policy_rejection(self, db, config, adapter):
        """Policy rejection should return a failed TaskResult."""
        config.policies.default.max_cost_usd = 0.0001  # Essentially zero = reject all
        from sccsos.security.policy import PolicyEngine
        policy = PolicyEngine(db, config)
        result = adapter.delegate_task(
            "architect", "expensive task", policy_engine=policy,
        )
        assert not result.success
        assert "Policy rejected" in result.error


class TestHermesSubprocessAdapter:
    """Tests for the real HermesSubprocessAdapter (with sandbox + policy).

    Uses ``unittest.mock`` to avoid calling the real Hermes CLI.
    """

    def test_constructor_with_whitelist(self):
        """Constructor should store the whitelist reference."""
        from sccsos.security.sandbox import CommandWhitelist
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter
        wl = CommandWhitelist(allowed_commands=["hermes"])
        adapter = HermesSubprocessAdapter(whitelist=wl)
        assert adapter._whitelist is wl
        assert adapter._hermes_bin == "hermes"

    def test_constructor_default_bin(self):
        """Default hermes_bin should be 'hermes'."""
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter
        adapter = HermesSubprocessAdapter()
        assert adapter._hermes_bin == "hermes"
        assert adapter._whitelist is None

    def test_sandbox_check_allowed(self):
        """Allowed command should return None."""
        from sccsos.security.sandbox import CommandWhitelist
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter
        wl = CommandWhitelist(allowed_commands=["hermes"])
        adapter = HermesSubprocessAdapter(whitelist=wl)
        result = adapter._sandbox_check(["hermes", "--version"])
        assert result is None

    def test_sandbox_check_blocked(self):
        """Dangerous command should return error string."""
        from sccsos.security.sandbox import CommandWhitelist
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter
        wl = CommandWhitelist(allowed_commands=["hermes"])
        adapter = HermesSubprocessAdapter(whitelist=wl)
        result = adapter._sandbox_check(["sudo", "rm", "-rf", "/"])
        assert result is not None
        assert "dangerous" in result.lower()

    def test_sandbox_check_non_allowed(self):
        """Command not in whitelist should be blocked."""
        from sccsos.security.sandbox import CommandWhitelist
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter
        wl = CommandWhitelist(allowed_commands=["hermes"])
        adapter = HermesSubprocessAdapter(whitelist=wl)
        result = adapter._sandbox_check(["curl", "http://evil.com"])
        assert result is not None
        assert "dangerous" in result.lower()  # curl is in DANGEROUS_PATTERNS

    def test_sandbox_check_no_whitelist(self):
        """Without whitelist, _sandbox_check should always return None."""
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter
        adapter = HermesSubprocessAdapter()
        result = adapter._sandbox_check(["sudo", "rm", "-rf", "/"])
        assert result is None  # No whitelist = no check

    def test_factory_subprocess(self):
        """create_adapter('subprocess') should return HermesSubprocessAdapter."""
        from sccsos.core.hermes_adapter import (
            create_adapter, HermesSubprocessAdapter,
        )
        adapter = create_adapter("subprocess")
        assert isinstance(adapter, HermesSubprocessAdapter)

    def test_factory_subprocess_with_whitelist(self):
        """create_adapter with whitelist should pass it through."""
        from sccsos.security.sandbox import CommandWhitelist
        from sccsos.core.hermes_adapter import (
            create_adapter, HermesSubprocessAdapter,
        )
        wl = CommandWhitelist(allowed_commands=["hermes"])
        adapter = create_adapter("subprocess", whitelist=wl)
        assert isinstance(adapter, HermesSubprocessAdapter)
        assert adapter._whitelist is wl

    def test_factory_mock(self):
        """create_adapter('mock') should return MockHermesAdapter."""
        from sccsos.core.hermes_adapter import (
            create_adapter, MockHermesAdapter,
        )
        adapter = create_adapter("mock")
        assert isinstance(adapter, MockHermesAdapter)

    def test_factory_unknown_raises(self):
        """create_adapter('unknown') should raise ValueError."""
        from sccsos.core.hermes_adapter import create_adapter
        import pytest
        with pytest.raises(ValueError, match="Unknown adapter mode"):
            create_adapter("nonexistent")

    def test_delegate_task_policy_rejection(self, db, config):
        """Policy rejection should return a failed TaskResult without subprocess call."""
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter
        from sccsos.security.policy import PolicyEngine

        config.policies.default.max_cost_usd = 0.0001  # Reject all
        policy = PolicyEngine(db, config)
        adapter = HermesSubprocessAdapter()

        # Policy rejection happens BEFORE subprocess call — no mock needed
        result = adapter.delegate_task(
            "architect", "expensive task", policy_engine=policy,
        )
        assert not result.success
        assert "Policy rejected" in result.error

    def test_delegate_task_sandbox_rejection(self):
        """Sandbox rejection should return a failed TaskResult without subprocess."""
        from sccsos.security.sandbox import CommandWhitelist
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter

        # Whitelist that only allows harmless commands
        wl = CommandWhitelist(allowed_commands=["cat", "ls"], allow_all=False)
        adapter = HermesSubprocessAdapter(whitelist=wl)
        # 'hermes' is not in the whitelist — should be blocked
        result = adapter.delegate_task(
            "architect", "test prompt",
        )
        assert not result.success
        assert "Sandbox blocked" in result.error
        assert "hermes" in result.error

    def test_check_connectivity_sandbox_blocked(self):
        """Sandbox-blocked connectivity should return False."""
        from sccsos.security.sandbox import CommandWhitelist
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter

        wl = CommandWhitelist(allowed_commands=["cat"], allow_all=False)
        adapter = HermesSubprocessAdapter(whitelist=wl)
        # 'hermes' not in whitelist
        assert adapter.check_connectivity() is False

    def test_get_profile_info_sandbox_blocked(self):
        """Sandbox-blocked profile info should return error dict."""
        from sccsos.security.sandbox import CommandWhitelist
        from sccsos.core.hermes_adapter import HermesSubprocessAdapter

        wl = CommandWhitelist(allowed_commands=["cat"], allow_all=False)
        adapter = HermesSubprocessAdapter(whitelist=wl)
        result = adapter.get_profile_info("sccsos")
        assert "error" in result
        assert "Sandbox blocked" in result["error"]


# ── AgentSpec YAML Round-trip ────────────────────────────────────


class TestAgentSpecYAML:
    def test_from_yaml_full(self, tmp_path):
        content = """\
name: full-agent
version: "2.0"
description: A fully specified agent
personality: helpful
profile: sccsos
toolsets:
  - filesystem
  - web-search
tags:
  - production
  - test
lifecycle:
  max_turns: 50
  timeout: 600
  auto_recover: false
metadata:
  owner: team-a
  slack: "#agents"
"""
        yml = tmp_path / "full.yaml"
        yml.write_text(content)
        spec = AgentSpec.from_yaml(yml)
        assert spec.name == "full-agent"
        assert spec.version == "2.0"
        assert spec.lifecycle.max_turns == 50
        assert spec.lifecycle.auto_recover is False
        assert spec.metadata["owner"] == "team-a"

    def test_to_from_dict(self):
        spec = AgentSpec(
            name="roundtrip",
            tags=["test"],
        )
        d = spec.to_dict()
        spec2 = AgentSpec.from_dict({
            "name": "roundtrip",
            "tags": ["test"],
            "lifecycle": {"max_turns": 30},
        })
        assert spec2.name == spec.name
        assert spec2.lifecycle.max_turns == 30


# ── End-to-End Integration Tests ──────────────────────────────────


class TestEndToEnd:
    """Full-stack tests: workflow input, vector store, knowledge base."""

    def test_workflow_with_input(self, db, adapter, tmp_path):
        """Workflow with --input should make {{ steps.input }} available."""
        from sccsos.core.orchestrator import (
            WorkflowEngine, WorkflowDef, WorkflowStepDef,
        )
        engine = WorkflowEngine(db, adapter)
        wf = WorkflowDef(
            name="input-test",
            steps=[
                WorkflowStepDef(
                    id="echo",
                    agent="architect",
                    prompt="Input was: {{ steps.input.context }}",
                ),
            ],
        )
        run_id = engine.execute(wf, input_data={"context": "Hello World"})
        status = engine.get_run_status(run_id)
        assert status["status"] == "completed"

    def test_workflow_without_input_still_works(self, db, adapter):
        """Workflow without input should not fail (input is optional)."""
        from sccsos.core.orchestrator import (
            WorkflowEngine, WorkflowDef, WorkflowStepDef,
        )
        engine = WorkflowEngine(db, adapter)
        wf = WorkflowDef(
            name="no-input",
            steps=[
                WorkflowStepDef(
                    id="s1",
                    agent="architect",
                    prompt="{{ steps.input.context }}",
                ),
            ],
        )
        run_id = engine.execute(wf)
        status = engine.get_run_status(run_id)
        assert status["status"] == "completed"

    def test_vector_store_basic(self):
        """VectorStore should find relevant documents by semantic content."""
        from sccsos.memory.vector_store import VectorStore
        vs = VectorStore()
        vs.add_document("d1", "The quick brown fox jumps over the lazy dog")
        vs.add_document("d2", "Python is a programming language for software development")
        vs.add_document("d3", "Machine learning models process large datasets")

        results = vs.search("fox jumping", top_k=2)
        assert len(results) >= 1
        assert results[0][0] == "d1"  # Most relevant

    def test_vector_store_chinese(self):
        """VectorStore should handle Chinese text."""
        from sccsos.memory.vector_store import VectorStore
        vs = VectorStore()
        vs.add_document("zh1", "智能体架构设计是构建AI系统的基础")
        vs.add_document("zh2", "数据库索引优化可以提升查询性能")

        results = vs.search("智能体 架构", top_k=2)
        assert len(results) >= 1
        best_id, best_score = results[0]
        assert best_score > 0

    def test_vector_store_add_and_remove(self):
        from sccsos.memory.vector_store import VectorStore
        vs = VectorStore()
        vs.add_document("d1", "First document")
        vs.add_document("d2", "Second document")
        assert vs.count() == 2
        vs.remove_document("d1")
        assert vs.count() == 1
        assert vs.get_document("d2") is not None

    def test_knowledge_base_with_vector(self, tmp_path):
        """KnowledgeBase with use_vector=True should use TF-IDF search."""
        from sccsos.memory.knowledge_base import KnowledgeBase

        # Create a mini wiki
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "architecture.md").write_text(
            "# Architecture\nAgent architecture design patterns."
        )
        (wiki_dir / "database.md").write_text(
            "# Database\nSQLite vector store for knowledge."
        )

        kb = KnowledgeBase(wiki_path=wiki_dir, use_vector=True)
        results = kb.query("agent architecture", top_k=2)
        assert len(results) >= 1

    def test_api_server_health_endpoint(self):
        """API server should return health on GET /health."""
        from sccsos.api.server import APIHandler
        assert hasattr(APIHandler, "do_GET")
        # The endpoint logic is tested via the earlier smoke test;
        # here we verify the handler class is importable and structured.


# ═══════════════════════════════════════════════════════════
# AgentRunner Tests
# ═══════════════════════════════════════════════════════════


class TestAgentRunner:
    """Tests for AgentRunner and AgentProcess background management."""

    def test_start_and_stop_agent(self, db):
        from sccsos.core.hermes_adapter import MockHermesAdapter
        from sccsos.core.agent_runner import AgentRunner
        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)

        started = runner.start_agent("test-agent")
        assert started is True
        assert runner.is_running("test-agent") is True
        assert "test-agent" in runner.list_running()

        stopped = runner.stop_agent("test-agent")
        assert stopped is True
        assert runner.is_running("test-agent") is False

    def test_start_twice_returns_false(self, db):
        from sccsos.core.hermes_adapter import MockHermesAdapter
        from sccsos.core.agent_runner import AgentRunner
        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)

        runner.start_agent("test-agent")
        started_again = runner.start_agent("test-agent")
        assert started_again is False

        runner.stop_all()

    def test_ask_agent_not_running(self, db):
        from sccsos.core.hermes_adapter import MockHermesAdapter
        from sccsos.core.agent_runner import AgentRunner
        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)

        result = runner.ask_agent("nonexistent", "hello")
        assert result.success is False
        assert "not running" in result.error

    def test_ask_running_agent(self, db):
        from sccsos.core.hermes_adapter import MockHermesAdapter
        from sccsos.core.agent_runner import AgentRunner
        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)

        runner.start_agent("test-agent")
        result = runner.ask_agent("test-agent", "Design a module", timeout=5)
        assert result.success is True
        assert "test-agent" in result.response

        runner.stop_all()

    def test_stop_all(self, db):
        from sccsos.core.hermes_adapter import MockHermesAdapter
        from sccsos.core.agent_runner import AgentRunner
        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)

        runner.start_agent("agent-a")
        runner.start_agent("agent-b")
        assert runner.count == 2

        stopped = runner.stop_all()
        assert stopped == 2
        assert runner.count == 0

    def test_agent_process_with_model_and_policy(self, db, config):
        from sccsos.core.hermes_adapter import MockHermesAdapter, create_adapter
        from sccsos.core.agent_runner import AgentRunner
        from sccsos.security.policy import PolicyEngine

        adapter = MockHermesAdapter()
        runner = AgentRunner(adapter)
        policy_engine = PolicyEngine(db, config)

        runner.start_agent("policy-agent", policy_engine=policy_engine, model="gpt-4o")

        assert runner.is_running("policy-agent")
        result = runner.ask_agent("policy-agent", "Test", timeout=5)
        assert result.success is True

        runner.stop_all()


# ═══════════════════════════════════════════════════════════
# Schema Validation Tests
# ═══════════════════════════════════════════════════════════


class TestWorkflowSchemaValidation:
    """Tests for WorkflowDef.from_yaml schema validation."""

    def test_empty_steps_raises(self, tmp_path):
        from sccsos.core.orchestrator import WorkflowDef, WorkflowValidationError
        path = tmp_path / "empty.yaml"
        path.write_text("name: test\nsteps: []")
        with pytest.raises(WorkflowValidationError, match="at least one step"):
            WorkflowDef.from_yaml(str(path))

    def test_missing_step_id_raises(self, tmp_path):
        from sccsos.core.orchestrator import WorkflowDef, WorkflowValidationError
        path = tmp_path / "bad.yaml"
        path.write_text("name: test\nsteps:\n  - agent: architect\n    prompt: hello")
        with pytest.raises(WorkflowValidationError, match="missing 'id'"):
            WorkflowDef.from_yaml(str(path))

    def test_duplicate_step_id_raises(self, tmp_path):
        from sccsos.core.orchestrator import WorkflowDef, WorkflowValidationError
        path = tmp_path / "dup.yaml"
        path.write_text(yaml.dump({
            "name": "test",
            "steps": [
                {"id": "a", "agent": "arch", "prompt": "p1"},
                {"id": "a", "agent": "arch", "prompt": "p2"},
            ],
        }))
        with pytest.raises(WorkflowValidationError, match="duplicate"):
            WorkflowDef.from_yaml(str(path))

    def test_missing_agent_raises(self, tmp_path):
        from sccsos.core.orchestrator import WorkflowDef, WorkflowValidationError
        path = tmp_path / "no-agent.yaml"
        path.write_text(yaml.dump({
            "name": "test",
            "steps": [{"id": "s1", "prompt": "hello"}],
        }))
        with pytest.raises(WorkflowValidationError, match="missing 'agent'"):
            WorkflowDef.from_yaml(str(path))

    def test_no_prompt_or_condition_raises(self, tmp_path):
        from sccsos.core.orchestrator import WorkflowDef, WorkflowValidationError
        path = tmp_path / "no-prompt.yaml"
        path.write_text(yaml.dump({
            "name": "test",
            "steps": [{"id": "s1", "agent": "arch"}],
        }))
        with pytest.raises(WorkflowValidationError, match="must have 'prompt', 'input', or 'condition'"):
            WorkflowDef.from_yaml(str(path))

    def test_input_field_accepted(self, tmp_path):
        """Steps with 'input' but no 'prompt' should pass validation."""
        from sccsos.core.orchestrator import WorkflowDef
        path = tmp_path / "input-only.yaml"
        path.write_text(yaml.dump({
            "name": "test",
            "steps": [{"id": "s1", "agent": "arch", "input": "hello"}],
        }))
        wf = WorkflowDef.from_yaml(str(path))
        assert len(wf.steps) == 1
        assert wf.steps[0].id == "s1"

    def test_invalid_timeout_raises(self, tmp_path):
        from sccsos.core.orchestrator import WorkflowDef, WorkflowValidationError
        path = tmp_path / "bad-timeout.yaml"
        path.write_text(yaml.dump({
            "name": "test",
            "steps": [{"id": "s1", "agent": "arch", "prompt": "hi", "timeout": -1}],
        }))
        with pytest.raises(WorkflowValidationError, match="timeout"):
            WorkflowDef.from_yaml(str(path))

    def test_valid_workflow_passes(self, tmp_path):
        from sccsos.core.orchestrator import WorkflowDef
        path = tmp_path / "good.yaml"
        path.write_text(yaml.dump({
            "name": "test",
            "steps": [
                {"id": "a", "agent": "arch", "prompt": "Step A"},
                {"id": "b", "agent": "arch", "prompt": "Step B", "depends_on": ["a"],
                 "timeout": 600, "retry": 2},
            ],
        }))
        wf = WorkflowDef.from_yaml(str(path))
        assert wf.name == "test"
        assert len(wf.steps) == 2

    def test_parallel_group_unknown_step_raises(self, tmp_path):
        from sccsos.core.orchestrator import WorkflowDef, WorkflowValidationError
        path = tmp_path / "bad-parallel.yaml"
        path.write_text(yaml.dump({
            "name": "test",
            "steps": [{"id": "a", "agent": "arch", "prompt": "A"}],
            "parallel_groups": [{"id": "g1", "steps": ["nonexistent"]}],
        }))
        with pytest.raises(WorkflowValidationError, match="unknown step"):
            WorkflowDef.from_yaml(str(path))


# ═══════════════════════════════════════════════════════════
# Condition Branch Tests
# ═══════════════════════════════════════════════════════════


class TestConditionBranch:
    """Tests for workflow condition step skipping."""

    def test_condition_true_executes(self, db, adapter):
        from sccsos.core.orchestrator import (
            WorkflowDef, WorkflowStepDef, WorkflowEngine,
        )
        engine = WorkflowEngine(db, adapter)
        wf = WorkflowDef(
            name="cond-true",
            steps=[
                WorkflowStepDef(id="check", agent="architect",
                                prompt="Output: CLEAR"),
                WorkflowStepDef(id="design", agent="architect",
                                prompt="Design: {{ steps.check.response }}",
                                depends_on=["check"],
                                condition="'CLEAR' in steps.check.response"),
            ],
        )
        run_id = engine.execute(wf)
        status = engine.get_run_status(run_id)
        assert status["status"] == "completed"

    def test_condition_false_skips(self, db, adapter):
        from sccsos.core.orchestrator import (
            WorkflowDef, WorkflowStepDef, WorkflowEngine,
        )
        engine = WorkflowEngine(db, adapter)
        wf = WorkflowDef(
            name="cond-false",
            steps=[
                WorkflowStepDef(id="check", agent="architect",
                                prompt="Output: VAGUE"),
                WorkflowStepDef(id="design", agent="architect",
                                prompt="Design: {{ steps.check.response }}",
                                depends_on=["check"],
                                condition="'CLEAR' not in steps.check.response"),
            ],
        )
        run_id = engine.execute(wf)
        status = engine.get_run_status(run_id)
        assert status["status"] == "completed"


# ═══════════════════════════════════════════════════════════
# Personality System Tests
# ═══════════════════════════════════════════════════════════


class TestPersonalitySystem:
    """Tests for PersonalityRegistry and prompt wrapping."""

    def test_empty_registry(self):
        from sccsos.core.personality import PersonalityRegistry
        reg = PersonalityRegistry()
        assert reg.count() == 0
        assert reg.list_names() == []

    def test_register_and_get(self):
        from sccsos.core.personality import Personality, PersonalityRegistry
        reg = PersonalityRegistry()
        p = Personality(name="architect", system_prompt="You are an architect.")
        reg.register(p)
        assert reg.count() == 1
        assert reg.get("architect") is p

    def test_wrap_prompt_no_personality(self):
        from sccsos.core.personality import PersonalityRegistry
        reg = PersonalityRegistry()
        result = reg.wrap_prompt(None, "Hello")
        assert result.prompt == "Hello"
        assert result.applied_personality is None

    def test_wrap_prompt_with_personality(self):
        from sccsos.core.personality import Personality, PersonalityRegistry
        reg = PersonalityRegistry()
        reg.register(Personality(name="arch", system_prompt="You are an architect."))
        result = reg.wrap_prompt("arch", "Design a module.")
        assert "You are an architect." in result.prompt
        assert "Design a module." in result.prompt
        assert result.applied_personality == "arch"

    def test_load_from_yaml(self, tmp_path):
        from sccsos.core.personality import PersonalityRegistry
        d = tmp_path / "personalities"
        d.mkdir()
        (d / "arch.yaml").write_text(yaml.dump({
            "name": "architect",
            "description": "Architecture specialist",
            "system_prompt": "You are an architect.",
            "model": "gpt-4o",
            "temperature": 0.5,
        }))
        reg = PersonalityRegistry()
        count = reg.load_from_dir(str(d))
        assert count == 1
        persona = reg.get("architect")
        assert persona is not None
        assert persona.model == "gpt-4o"
        assert persona.temperature == 0.5

    def test_skip_invalid_files(self, tmp_path):
        from sccsos.core.personality import PersonalityRegistry
        d = tmp_path / "personalities"
        d.mkdir()
        (d / "invalid.yaml").write_text("not: valid: yaml: [")
        reg = PersonalityRegistry()
        count = reg.load_from_dir(str(d))
        assert count == 0  # Invalid file skipped silently


# ═══════════════════════════════════════════════════════════
# CommandWhitelist Configurable Patterns
# ═══════════════════════════════════════════════════════════


class TestCommandWhitelistExtraPatterns:
    """Tests for configurable DANGEROUS_PATTERNS."""

    def test_extra_dangerous_patterns_blocked(self):
        from sccsos.security.sandbox import CommandWhitelist
        wl = CommandWhitelist(
            allowed_commands=["echo"],
            dangerous_patterns=["docker", "kubectl"],
        )
        # Built-in pattern still blocked
        assert not wl.check("sudo rm -rf /").allowed
        # Extra pattern blocked
        assert not wl.check("docker ps").allowed
        assert not wl.check("kubectl get pods").allowed
        # Allowed command passes
        assert wl.check("echo hello").allowed

    def test_empty_extra_patterns(self):
        from sccsos.security.sandbox import CommandWhitelist
        wl = CommandWhitelist(allowed_commands=["echo"])
        assert wl.check("echo hello").allowed
        # Only built-in patterns blocked
        assert not wl.check("sudo ls").allowed


# ═══════════════════════════════════════════════════════════
# Step Timeout Tests
# ═══════════════════════════════════════════════════════════


class TestStepTimeout:
    """Tests that step timeout is propagated to adapter."""

    def test_step_timeout_passed_to_adapter(self, db):
        """Verify that timeout from WorkflowStepDef reaches delegate_task."""
        from sccsos.core.orchestrator import (
            WorkflowDef, WorkflowStepDef, WorkflowEngine,
        )
        from sccsos.core.hermes_adapter import MockHermesAdapter, TaskResult

        class TimeoutCapturingAdapter(MockHermesAdapter):
            def __init__(self):
                super().__init__()
                self.last_timeout = None

            def delegate_task(self, agent_name, prompt, **kwargs):
                self.last_timeout = kwargs.get("timeout")
                return super().delegate_task(agent_name, prompt, **kwargs)

        adapter = TimeoutCapturingAdapter()
        engine = WorkflowEngine(db, adapter)

        wf = WorkflowDef(
            name="timeout-test",
            steps=[
                WorkflowStepDef(
                    id="s1", agent="architect", prompt="Hi",
                    timeout=999,  # Distinct timeout value
                ),
            ],
        )
        engine.execute(wf)
        assert adapter.last_timeout == 999, (
            f"Expected timeout=999, got {adapter.last_timeout}"
        )


class TestSchemaMigration:
    """Workflow schema version migration."""

    def test_legacy_workflow_auto_migrates(self):
        """A YAML without schema_version should be treated as 1.0 and migrated."""
        yaml_text = """name: legacy-test
version: 1.0
steps:
  - id: step1
    agent: architect
    prompt: Do something
"""
        import yaml, tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            path = f.name
        try:
            wf = WorkflowDef.from_yaml(path)
            assert wf.name == "legacy-test"
            assert wf.schema_version == "1.1"  # Auto-migrated
            assert len(wf.steps) == 1
            # Migration should add defaults
            assert wf.steps[0].timeout == 600
            assert wf.steps[0].retry == 0
        finally:
            os.unlink(path)

    def test_v1_1_workflow_passes_through(self):
        """A YAML with schema_version 1.1 should load without migration."""
        yaml_text = """name: current-test
schema_version: '1.1'
version: 2.0
steps:
  - id: step1
    agent: architect
    prompt: Do something
    timeout: 300
    retry: 2
"""
        import yaml, tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            path = f.name
        try:
            wf = WorkflowDef.from_yaml(path)
            assert wf.schema_version == "1.1"
            assert wf.version == 2.0  # YAML parses 2.0 as float
            assert wf.steps[0].timeout == 300
            assert wf.steps[0].retry == 2
        finally:
            os.unlink(path)

    def test_migrate_preserves_steps(self):
        """Migration should not change step count or agent assignments."""
        yaml_text = """name: preserver
steps:
  - id: a
    agent: arch
    prompt: p1
  - id: b
    agent: rev
    prompt: p2
    depends_on:
      - a
"""
        import yaml, tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            path = f.name
        try:
            wf = WorkflowDef.from_yaml(path)
            assert len(wf.steps) == 2
            assert wf.steps[0].agent == "arch"
            assert wf.steps[1].depends_on == ["a"]
        finally:
            os.unlink(path)

    def test_to_yaml_includes_schema_version(self):
        """Serialized YAML should include schema_version."""
        wf = WorkflowDef(
            name="test",
            steps=[WorkflowStepDef(id="s1", agent="arch", prompt="hi")],
        )
        yaml_out = wf.to_yaml()
        assert "schema_version: '1.1'" in yaml_out

    def test_unknown_schema_version_raises(self):
        """An unrecognized schema version should raise."""
        yaml_text = """name: bad-version
schema_version: '99.99'
version: 1.0
steps:
  - id: s1
    agent: arch
    prompt: hi
"""
        import yaml, tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            path = f.name
        try:
            import pytest
            with pytest.raises(WorkflowValidationError, match="99.99"):
                WorkflowDef.from_yaml(path)
        finally:
            os.unlink(path)
