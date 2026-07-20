"""Backward-compatible shim — CLI system commands now live in individual modules.

- trace commands      → ``sccsos.cli.trace_cmd``
- audit commands      → ``sccsos.cli.audit_cmd``
- memory commands     → ``sccsos.cli.memory_cmd``
- session commands    → ``sccsos.cli.session_cmd``
- personality commands → ``sccsos.cli.personality_cmd``

New code should import from the individual modules directly.
"""

from sccsos.cli.trace_cmd import trace
from sccsos.cli.audit_cmd import audit
from sccsos.cli.memory_cmd import memory
from sccsos.cli.session_cmd import session
from sccsos.cli.personality_cmd import personality

__all__ = ["trace", "audit", "memory", "session", "personality"]
