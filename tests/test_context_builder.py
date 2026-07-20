"""Tests for ContextBuilder — template context assembly."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sccsos.core.context_builder import ContextBuilder


@pytest.fixture
def basic_step():
    return SimpleNamespace(agent="test-agent", name="step1", prompt="hello")


class TestContextBuilder:
    """ContextBuilder edge cases and feature tests."""

    def test_basic_context(self):
        """Builds context with steps and run_id."""
        cb = ContextBuilder()
        step = SimpleNamespace(agent="a1", name="s1", prompt="hi")
        ctx, render_fn = cb.build(step, {"prev": {"response": "ok"}}, "run-1")

        assert ctx["steps"] == {"prev": {"response": "ok"}}
        assert ctx["run_id"] == "run-1"
        assert "knowledge" not in ctx
        assert "memory" not in ctx
        assert callable(render_fn)

    def test_empty_step_outputs(self):
        """Works with empty step outputs dict."""
        cb = ContextBuilder()
        step = SimpleNamespace(agent="a1", name="s1", prompt="hi")
        ctx, _ = cb.build(step, {}, "run-empty")
        assert ctx["steps"] == {}

    def test_knowledge_injection(self):
        """Knowledge base context is injected when available."""
        class FakeKB:
            def get_context_for(self, query):
                return {"wiki": "Relevant knowledge"}

        cb = ContextBuilder(knowledge_base=FakeKB())
        step = SimpleNamespace(agent="a1", name="s1", prompt="question")
        ctx, _ = cb.build(step, {}, "run-kb")
        assert ctx["knowledge"] == {"wiki": "Relevant knowledge"}

    def test_kb_returns_none(self):
        """Knowledge base returning None/empty does not set key."""
        class FakeKBEmpty:
            def get_context_for(self, query):
                return None

        cb = ContextBuilder(knowledge_base=FakeKBEmpty())
        step = SimpleNamespace(agent="a1", name="s1", prompt="q")
        ctx, _ = cb.build(step, {}, "run-empty-kb")
        assert "knowledge" not in ctx

    def test_kb_returns_empty_dict(self):
        """Knowledge base returning empty dict does not set key."""
        class FakeKBEmptyDict:
            def get_context_for(self, query):
                return {}

        cb = ContextBuilder(knowledge_base=FakeKBEmptyDict())
        step = SimpleNamespace(agent="a1", name="s1", prompt="q")
        ctx, _ = cb.build(step, {}, "run-empty-kbdict")
        assert "knowledge" not in ctx

    def test_memory_injection(self):
        """Persistent memory is injected when available."""
        class FakeMemory:
            def get_all(self, agent):
                return {"language": "Python", "framework": "FastAPI"}

        cb = ContextBuilder(memory_store=FakeMemory())
        step = SimpleNamespace(agent="coder", name="s1", prompt="write")
        ctx, _ = cb.build(step, {}, "run-mem")
        assert ctx["memory"] == {"language": "Python", "framework": "FastAPI"}

    def test_memory_returns_none(self):
        """Memory returning None does not set key."""
        class FakeMemoryNone:
            def get_all(self, agent):
                return None

        cb = ContextBuilder(memory_store=FakeMemoryNone())
        step = SimpleNamespace(agent="coder", name="s1", prompt="write")
        ctx, _ = cb.build(step, {}, "run-mem-none")
        assert "memory" not in ctx

    def test_both_kb_and_memory(self):
        """Both KB and memory are injected when both configured."""
        class FakeKB:
            def get_context_for(self, query):
                return {"topic": "AI"}

        class FakeMemory:
            def get_all(self, agent):
                return {"pref": "concise"}

        cb = ContextBuilder(
            knowledge_base=FakeKB(),
            memory_store=FakeMemory(),
        )
        step = SimpleNamespace(agent="a1", name="s1", prompt="q")
        ctx, _ = cb.build(step, {}, "run-both")
        assert ctx["knowledge"] == {"topic": "AI"}
        assert ctx["memory"] == {"pref": "concise"}

    def test_custom_template_engine(self):
        """Custom render function is used when injected."""
        def fake_render(template, context):
            return f"RENDERED: {template}"

        cb = ContextBuilder(template_engine=fake_render)
        step = SimpleNamespace(agent="a1", name="s1", prompt="hello")
        _, render_fn = cb.build(step, {}, "run-custom")
        assert render_fn("hello", {}) == "RENDERED: hello"

    def test_multiple_steps_preserved(self):
        """All previous step outputs are preserved."""
        cb = ContextBuilder()
        step = SimpleNamespace(agent="a1", name="s1", prompt="q")
        outputs = {"s1": {"response": "first"}, "s2": {"response": "second"}}
        ctx, _ = cb.build(step, outputs, "run-multi")
        assert ctx["steps"]["s1"]["response"] == "first"
        assert ctx["steps"]["s2"]["response"] == "second"
