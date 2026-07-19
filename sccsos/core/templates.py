"""Jinja2 Template Engine — sandboxed template rendering for workflows.

Extracted from orchestrator.py to reduce module size and enable
independent testing of the template layer.

Custom filters registered on the environment:

========================  ============================================
Filter                    Description
========================  ============================================
``json_parse``            Parse a JSON string into a Python object.
``json_dumps``            Serialize a Python object to JSON string.
``pick``                  Extract a field from a dict.
``strptime``              Parse ISO datetime to ``datetime`` object.
``strftime``              Format a ``datetime`` with strftime pattern.
``truncate_cn``           Truncate text respecting CJK character widths.
========================  ============================================

Usage:
    from sccsos.core.templates import _render_template
    rendered = _render_template("Hello {{ name }}", {"name": "World"})
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from jinja2 import Environment, Undefined
from jinja2.sandbox import SandboxedEnvironment


# ── Custom Jinja2 Filters ──────────────────────────────────────────


def filter_json_parse(value: str) -> Any:
    """Parse a JSON string into a Python dict/list.

    Usage in workflow templates::

        {{ steps.api_result.response | json_parse }}

    Returns the parsed object.  Raises ``ValueError`` for invalid JSON.
    """
    if not isinstance(value, str):
        return value
    return json.loads(value)


def filter_json_dumps(value: Any, indent: int = 2) -> str:
    """Serialize a Python object to a formatted JSON string.

    Usage::

        {{ steps.input.data | json_dumps }}

    Args:
        value: Object to serialize.
        indent: Pretty-print indent level (default 2).  Pass 0 for
            compact output (no extra whitespace).

    Returns:
        JSON string, or the original value if serialization fails.
    """
    try:
        return json.dumps(value, ensure_ascii=False, indent=indent,
                          default=str)
    except (TypeError, ValueError):
        return str(value)


def filter_pick(value: dict[str, Any], key: str,
                default: Any = "") -> Any:
    """Extract a field from a dict safely.

    Usage::

        {{ steps.step1.response | pick('data') }}
        {{ steps.step1.response | pick('items', default=[]) }}

    Args:
        value: The dict to extract from (typically ``steps.X.response``).
        key: The field name to extract.
        default: Value returned if the key is missing (default ``""``).

    Returns:
        The field value, or ``default`` if the key is not present.
    """
    if not isinstance(value, dict):
        return default
    return value.get(key, default)


def filter_strptime(value: str, fmt: str = "%Y-%m-%dT%H:%M:%S") -> datetime:
    """Parse an ISO datetime string into a ``datetime`` object.

    Usage::

        {{ steps.start_time | strptime }}
        {{ "2026-07-20" | strptime("%Y-%m-%d") }}

    Args:
        value: Datetime string.
        fmt: strftime format string (default ISO with seconds).

    Returns:
        ``datetime.datetime`` object (usable with ``| strftime``).
    """
    if isinstance(value, datetime):
        return value
    # Try ISO format first (most common in workflow data)
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        pass
    # Fall back to explicit format
    return datetime.strptime(value, fmt)


def filter_strftime(value: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format a ``datetime`` object as a string.

    Usage::

        {{ steps.start_time | strptime | strftime("%Y-%m-%d") }}

    Args:
        value: ``datetime`` object (often from ``| strptime``).
        fmt: strftime format string (default ``"%Y-%m-%d %H:%M:%S"``).

    Returns:
        Formatted date string.
    """
    if not isinstance(value, datetime):
        return str(value)
    try:
        return value.strftime(fmt)
    except (ValueError, TypeError):
        return str(value)


def filter_truncate_cn(value: str, length: int = 100,
                       ellipsis: str = "...") -> str:
    """Truncate text, treating CJK characters as width-2.

    Standard ``truncate`` counts every character as 1, which gives
    incorrect results for mixed Chinese/English text. This filter
    treats CJK characters as width 2 for accurate truncation.

    Usage::

        {{ long_text | truncate_cn(80) }}

    Args:
        value: Text to truncate.
        length: Max display width (default 100).
        ellipsis: Suffix when truncated (default ``"..."``).

    Returns:
        Truncated string.
    """
    if not isinstance(value, str):
        return str(value)
    width = 0
    for i, ch in enumerate(value):
        ch_width = 2 if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' else 1
        if width + ch_width > length:
            return value[:i] + ellipsis
        width += ch_width
    return value


# ── Custom filter registry ─────────────────────────────────────────

CUSTOM_FILTERS: dict[str, Any] = {
    "json_parse": filter_json_parse,
    "json_dumps": filter_json_dumps,
    "pick": filter_pick,
    "strptime": filter_strptime,
    "strftime": filter_strftime,
    "truncate_cn": filter_truncate_cn,
}

__all__ = list(CUSTOM_FILTERS.keys()) + [
    "_render_template", "_create_jinja_env",
    "TemplateRenderError",
]


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
    - Custom filters: ``json_parse``, ``json_dumps``, ``pick``,
      ``strptime``, ``strftime``, ``truncate_cn``
    """
    env = SandboxedEnvironment(autoescape=False)
    env.undefined = Undefined
    env.filters.update(CUSTOM_FILTERS)
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
      - Built-in filters:    ``{{ name|upper }}``, ``{{ steps.a.response|truncate(100) }}``
      - Custom filters:      ``{{ steps.api.response | json_parse }}``
                             ``{{ steps.input.data | pick('context') }}``
                             ``{{ "2026-07-20" | strptime("%Y-%m-%d") | strftime }}``
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
            f"  {i + 1}: {line}" for i, line in enumerate(lines)
        )
        available_keys = list(context.keys())
        raise TemplateRenderError(
            f"Template render failed: {e}\n"
            f"Available context keys: {available_keys}\n"
            f"Template snippet:\n{snippet}"
        ) from e
