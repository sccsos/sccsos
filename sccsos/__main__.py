"""sccsos — SCCS Operating System CLI entry point.

Usage:
    python -m sccsos serve          # FastAPI server (default, requires sccsos[api])
    python -m sccsos serve --legacy # Legacy http.server (deprecated)
    python -m sccsos agent list     # Agent management
    python -m sccsos workflow run   # Workflow execution
    python -m sccsos                # Show CLI help
"""

from sccsos.cli import main

if __name__ == "__main__":
    main()
