#!/usr/bin/env python3
"""Extract release notes for a given version from CHANGELOG.md.

Usage: python3 scripts/extract_release_notes.py <version> [output_path]
"""

import re
import sys
from pathlib import Path


def extract_notes(version: str, changelog_path: str = "CHANGELOG.md") -> str:
    """Extract the release notes section for a given version.

    Returns the section body between the version header and next header.
    """
    content = Path(changelog_path).read_text(encoding="utf-8")
    pattern = rf"## \[{re.escape(version)}\] — (.*?)\n(.+?)(?=\n## \[|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return f"sccsos v{version} — 自动发布"
    body = match.group(2).strip()
    if len(body) > 64000:
        body = body[:64000] + "\n\n... (truncated)"
    return body


def main():
    if len(sys.argv) < 2:
        print("Usage: extract_release_notes.py <version> [output_path]", file=sys.stderr)
        sys.exit(1)

    version = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else None

    notes = extract_notes(version)
    if output:
        Path(output).write_text(notes, encoding="utf-8")
        print(f"Release notes written: {output} ({len(notes)} chars)")
    else:
        print(notes)


if __name__ == "__main__":
    main()
