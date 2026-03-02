#!/usr/bin/env bash
# Install pre-commit hooks and all supporting dev tooling.
#
# Usage:
#   bash scripts/install_hooks.sh
#
# What this does:
#   1. Installs dev dependencies (pre-commit, ruff, detect-secrets, deptry)
#   2. Generates or updates the detect-secrets baseline
#   3. Installs the pre-commit hooks into .git/hooks/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo "==> Installing dev dependencies..."
pip install -r requirements-dev.txt --quiet

echo "==> Generating detect-secrets baseline..."
if [ -f ".secrets.baseline" ]; then
    # Update existing baseline (keeps acknowledged false-positives)
    detect-secrets scan --update .secrets.baseline \
        --exclude-files '\.secrets\.baseline' \
        --exclude-files 'docs/.*' \
        --exclude-files '.*\.lock'
else
    # Create fresh baseline
    detect-secrets scan \
        --exclude-files '\.secrets\.baseline' \
        --exclude-files 'docs/.*' \
        --exclude-files '.*\.lock' \
        > .secrets.baseline
fi
echo "    Baseline written to .secrets.baseline"

echo "==> Installing pre-commit hooks..."
pre-commit install

echo ""
echo "Done! Hooks are active for every commit."
echo "To run all hooks manually:  pre-commit run --all-files"
