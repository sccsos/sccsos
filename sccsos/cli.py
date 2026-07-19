"""AgentOS CLI — backward-compatible entry point.

All command implementations have been split into ``sccsos/cli/``
for maintainability. This file re-exports the ``main()`` entry
point that pyproject.toml references.

Usage:
    python -m sccsos.cli          # Entry for ``sccsos`` command
    python -m sccsos.cli agent list
"""
from __future__ import annotations

from sccsos.cli import main

if __name__ == "__main__":
    main()
