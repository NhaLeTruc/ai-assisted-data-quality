#!/usr/bin/env bash
# Install pre-commit hooks and all supporting dev tooling.
#
# Usage:
#   bash scripts/install_hooks.sh
#
# What this does:
#   1. Resolves pip/python/pre-commit from .venv if present, otherwise PATH
#   2. Installs dev dependencies (pre-commit, ruff, detect-secrets, deptry)
#   3. Generates or updates the detect-secrets baseline
#   4. Installs the pre-commit hooks into .git/hooks/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# ── Resolve tooling paths ─────────────────────────────────────────────────────
if [ -f ".venv/bin/pip" ]; then
    PIP=".venv/bin/pip"
    DETECT_SECRETS=".venv/bin/detect-secrets"
    PRE_COMMIT=".venv/bin/pre-commit"
    echo "==> Using .venv at ${REPO_ROOT}/.venv"
else
    PIP="pip"
    DETECT_SECRETS="detect-secrets"
    PRE_COMMIT="pre-commit"
    echo "==> No .venv found — using system pip/pre-commit"
fi

# ── Install dev dependencies ──────────────────────────────────────────────────
echo "==> Installing dev dependencies..."
"${PIP}" install -r requirements-dev.txt --quiet

# ── Generate / update detect-secrets baseline ────────────────────────────────
echo "==> Generating detect-secrets baseline..."
if [ -f ".secrets.baseline" ]; then
    # Rescan and merge with existing baseline (keeps acknowledged false-positives)
    "${DETECT_SECRETS}" scan \
        --baseline .secrets.baseline \
        --exclude-files '\.secrets\.baseline' \
        --exclude-files 'docs/.*' \
        --exclude-files '.*\.lock'
else
    # Create fresh baseline
    "${DETECT_SECRETS}" scan \
        --exclude-files '\.secrets\.baseline' \
        --exclude-files 'docs/.*' \
        --exclude-files '.*\.lock' \
        > .secrets.baseline
fi
echo "    Baseline written to .secrets.baseline"

# ── Install pre-commit hooks ──────────────────────────────────────────────────
echo "==> Installing pre-commit hooks..."
"${PRE_COMMIT}" install

echo ""
echo "Done! Hooks are active for every commit."
echo "To run all hooks manually:  ${PRE_COMMIT} run --all-files"
