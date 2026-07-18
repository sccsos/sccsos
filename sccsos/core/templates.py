"""Jinja2 Template Engine — sandboxed template rendering for workflows.

Extracted from orchestrator.py to reduce module size and enable
independent testing of the template layer.

Usage:
    from sccsos.core.templates import _render_template
    rendered = _render_template("Hello {{ name }}", {"name": "World"})
"""

from __future__ import annotations

from jinja2 import Environment, Undefined
from jinja2.sandbox import SandboxedEnvironment


# ── Exceptions ─────────────────────────────────────────────────────


class TemplateRenderError(Exception):
    """Raised when a workflow template cannot be rendered."""
    pass


# ── Environment ────────────────────────────────────────────────────


def _create_jinja_env() -> Environment:
    """Create a sandboxed Jinja2 environment for workflow templates.

    - Sandboxed: unsafe operations (import, exec, file I/O) are blocked
    - Autoescape off: templates are prompt text, not HTML
    - Undefined: silently returns empty string for missing variables
      (preserving backward compatibility with old behaviour)
    """
    env = SandboxedEnvironment(autoescape=False)
    env.undefined = Undefined
    return env


# Singleton environment (created once)
_JINJA_ENV: Environment | None = None


def _get_jinja_env() -> Environment:
    global _JINJA_ENV
    if _JINJA_ENV is None:
        _JINJA_ENV = _create_jinja_env()
    return _JINJA_ENV


# ── Rendering ──────────────────────────────────────────────────────


def _render_template(template: str, context: dict) -> str:
    """Render a template string with Jinja2.

    Supports:
      - Variable access:     ``{{ steps.architecture-review.response }}``
      - Conditionals:        ``{% if done %}...{% endif %}``
      - Loops:               ``{% for item in items %}...{{ item }}...{% endfor %}``
      - Filters:             ``{{ name|upper }}``, ``{{ steps.a.response|truncate(100) }}``
      - Defaults:            ``{{ steps.a.response | default('(empty)') }}``
      - Dot-notation access: ``steps.architect.response`` (dict key access)

    Backward-compatible: existing ``{{ steps.xxx.response }}`` syntax
    works identically to before.

    Raises:
        TemplateRenderError: with template snippet + context keys on failure.
    """
    if not template or not template.strip():
        return template or ""

    # Quick path: no Jinja2 syntax → return as-is (avoids compile overhead)
    if "{{" not in template and "{%" not in template:
        return template

    env = _get_jinja_env()
    try:
        tpl = env.from_string(template)
        return tpl.render(**context)
    except Exception as e:
        # Extract a snippet for error context
        lines = template.split("\n")
        snippet = "\n".join(
            f"  {i+1}: {line}" for i, line in enumerate(lines)
        )
        available_keys = list(context.keys())
        raise TemplateRenderError(
            f"Template render failed: {e}\n"
            f"Available context keys: {available_keys}\n"
            f"Template snippet:\n{snippet}"
        ) from e
