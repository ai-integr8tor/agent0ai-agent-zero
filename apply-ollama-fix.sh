#!/usr/bin/env bash
# apply-ollama-fix.sh
#
# Re-applies the Ollama embedding fix after pulling a new agent-zero version.
# Upstream issue: https://github.com/agent0ai/agent-zero/issues/1425
# Remove this script once PR #1438 (or equivalent) is merged upstream.
#
# What it fixes:
#   1. Bypasses LiteLLM's broken Ollama handler (sends wrong model name + unsupported
#      kwargs), calling /api/embed directly instead.
#   2. Sanitizes None/non-str inputs before sending to Ollama (null in JSON → 400).
#   3. Retries only on transient errors (429/503), not on 400 (bad payload = no point).
#
# Usage:  ./apply-ollama-fix.sh [container-name]
#   container-name defaults to "agent-zero-normal"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH="$SCRIPT_DIR/ollama-embed-fix.patch"
ROOT_TARGET="$SCRIPT_DIR/models.py"
A0_TARGET="$SCRIPT_DIR/a0/models.py"
CONTAINER="${1:-agent-zero-normal}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { echo -e "${GREEN}[fix]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC} $*"; }
die()     { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

_restart_container() {
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER}$"; then
        info "Restarting container '$CONTAINER' ..."
        docker restart "$CONTAINER"
        info "Done. Container restarted with patched models.py."
    else
        warn "Container '$CONTAINER' not running — patch applied to disk only."
        warn "Start/restart the container manually when ready."
    fi
}

# ── Guard: already at latest patch version? ───────────────────────────────────
# Check for the Round 3 sanitization guard (safe_texts) — not just _ollama_embed.
if grep -q 'safe_texts' "$ROOT_TARGET" 2>/dev/null; then
    info "Latest patch already applied to $ROOT_TARGET — nothing to do."
    if [ -f "$A0_TARGET" ] && grep -q 'safe_texts' "$A0_TARGET" 2>/dev/null; then
        info "Latest patch already applied to $A0_TARGET — nothing to do."
        exit 0
    fi
    # a0/models.py exists but needs sync
    if [ -f "$A0_TARGET" ]; then
        info "Syncing $ROOT_TARGET → $A0_TARGET ..."
        cp "$ROOT_TARGET" "$A0_TARGET"
        info "Sync done."
        _restart_container
        exit 0
    fi
    exit 0
fi

info "Applying Ollama embedding fix to $ROOT_TARGET ..."

# Try git apply first (cleanest), fall back to patch(1)
if git -C "$SCRIPT_DIR" apply --check "$PATCH" 2>/dev/null; then
    git -C "$SCRIPT_DIR" apply "$PATCH"
    info "Applied via git apply."
elif patch --dry-run -p1 -d "$SCRIPT_DIR" < "$PATCH" 2>/dev/null; then
    patch -p1 -d "$SCRIPT_DIR" < "$PATCH"
    info "Applied via patch."
else
    die "Patch failed — the file may have diverged too much from the expected version.
Run 'patch --dry-run -p1 < ollama-embed-fix.patch' to see what conflicts.
You may need to re-generate the patch from the current models.py."
fi

# ── Sync patched root models.py → a0/models.py (Docker volume mount) ──────────
if [ -f "$A0_TARGET" ]; then
    info "Syncing $ROOT_TARGET → $A0_TARGET ..."
    cp "$ROOT_TARGET" "$A0_TARGET"
    info "Sync done."
else
    warn "a0/models.py not found — Docker volume may not be mounted yet."
    warn "After starting the container, run:  cp models.py a0/models.py"
fi

# ── Restart container so the running process picks up the new file ────────────
_restart_container
