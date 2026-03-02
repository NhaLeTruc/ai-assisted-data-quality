#!/usr/bin/env python3
"""Pre-commit hook: run deptry dependency health check.

Guards against missing requirements.txt (which won't exist until Phase 0).
Skips silently if requirements.txt does not exist yet.

Checks for:
  - Obsolete dependencies (declared but not imported)
  - Missing dependencies (imported but not declared)
  - Transitive dependencies used directly
"""

import subprocess
import sys
from pathlib import Path

REQUIREMENTS = Path("requirements.txt")
SRC_DIR = Path("src")


def main() -> int:
    if not REQUIREMENTS.exists():
        print(
            "[deptry] No requirements.txt found — skipping dependency check.",
            file=sys.stderr,
        )
        return 0

    if not SRC_DIR.exists():
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "deptry", str(SRC_DIR)],
        capture_output=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
