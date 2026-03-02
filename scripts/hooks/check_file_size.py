#!/usr/bin/env python3
"""Pre-commit hook: fail if any staged Python file exceeds MAX_LINES lines.

Usage (called automatically by pre-commit):
    python check_file_size.py <file1> <file2> ...
"""

import sys
from pathlib import Path

MAX_LINES = 500
# Files that are explicitly exempt (generated or legitimately large)
EXEMPT_SUFFIXES = (".min.js", ".min.css")
EXEMPT_NAMES = {"conftest.py"}


def check(paths: list[str]) -> int:
    violations: list[tuple[str, int]] = []

    for raw in paths:
        path = Path(raw)

        if path.name in EXEMPT_NAMES:
            continue
        if any(path.name.endswith(s) for s in EXEMPT_SUFFIXES):
            continue

        try:
            line_count = sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
        except OSError as exc:
            print(f"  warning: could not read {path}: {exc}", file=sys.stderr)
            continue

        if line_count > MAX_LINES:
            violations.append((str(path), line_count))

    if not violations:
        return 0

    print(f"\n[file-size] ERROR — files exceed {MAX_LINES}-line limit:", file=sys.stderr)
    for file_path, count in sorted(violations):
        over = count - MAX_LINES
        print(f"  {file_path}: {count} lines  (+{over} over limit)", file=sys.stderr)
    print(
        "\nSplit large files into smaller, focused modules before committing.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(check(sys.argv[1:]))
