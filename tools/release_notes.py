#!/usr/bin/env python3
"""Print one version's section of CHANGELOG.md (for its GitHub release).

    tools/release_notes.py 0.20.0
    tools/release_notes.py --versions    every version in the changelog, oldest first
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
HEADING = re.compile(r"^## (\d+\.\d+\.\d+)(?: \((\d{4}-\d{2}-\d{2})\))?\s*$")


def sections(text: str) -> dict[str, str]:
    """{version: its notes}, in the changelog's order (newest first)."""
    out: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        m = HEADING.match(line)
        if m or line.startswith("## "):
            if current:
                out[current] = "\n".join(lines).strip()
            current, lines = (m.group(1) if m else None), []
        elif current:
            lines.append(line)
    if current:
        out[current] = "\n".join(lines).strip()
    return out


def main(argv: list[str]) -> int:
    found = sections(CHANGELOG.read_text())
    if argv == ["--versions"]:
        print("\n".join(reversed(found)))
        return 0
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    notes = found.get(argv[0].removeprefix("v"))
    if notes is None:
        print(f"{argv[0]} isn't in CHANGELOG.md", file=sys.stderr)
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
