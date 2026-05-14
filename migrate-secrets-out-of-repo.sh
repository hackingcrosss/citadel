#!/bin/bash
# One-shot migration: moves SECRET_KEY / MASTER_ENCRYPTION_KEY (and *_LEGACY,
# if present) from the repo-local .env to an external secrets file so they
# never sit alongside source code.
#
# Default destination: $HOME/.config/citadel/secrets.env (user-owned, no sudo).
# Override with CITADEL_SECRETS_FILE=/some/path before running.
#
# Aborts if the destination already exists. The original .env is backed up
# before lines are stripped — restore it if anything goes wrong.

set -euo pipefail

cd "$(dirname "$0")"

SECRETS_FILE="${CITADEL_SECRETS_FILE:-$HOME/.config/citadel/secrets.env}"
SECRETS_DIR=$(dirname "$SECRETS_FILE")

if [ ! -f .env ]; then
    echo "[!] .env not found in $(pwd)" >&2
    exit 1
fi

if [ -f "$SECRETS_FILE" ]; then
    echo "[!] $SECRETS_FILE already exists; aborting to avoid clobbering it." >&2
    echo "    Inspect it. If it's stale, move it aside (mv ... .old) and re-run." >&2
    exit 1
fi

SECRET_LINES=$(grep -E '^(SECRET_KEY|MASTER_ENCRYPTION_KEY|MASTER_ENCRYPTION_KEY_LEGACY)=' .env || true)
if [ -z "$SECRET_LINES" ]; then
    echo "[!] No SECRET_KEY / MASTER_ENCRYPTION_KEY found in .env; nothing to migrate." >&2
    exit 1
fi

# Try to write without sudo; escalate only if needed.
if mkdir -p "$SECRETS_DIR" 2>/dev/null && touch "$SECRETS_FILE" 2>/dev/null; then
    SUDO=""
else
    echo "[+] $SECRETS_DIR requires elevated permissions; using sudo"
    SUDO="sudo"
    $SUDO mkdir -p "$SECRETS_DIR"
    $SUDO touch "$SECRETS_FILE"
fi

printf '%s\n' "$SECRET_LINES" | $SUDO tee "$SECRETS_FILE" > /dev/null
$SUDO chmod 0600 "$SECRETS_FILE"
$SUDO chown "$(id -u):$(id -g)" "$SECRETS_FILE"

BACKUP=.env.backup.pre-secrets-split.$(date +%Y%m%d-%H%M%S)
cp .env "$BACKUP"
sed -i '/^SECRET_KEY=/d; /^MASTER_ENCRYPTION_KEY=/d; /^MASTER_ENCRYPTION_KEY_LEGACY=/d' .env

echo ""
echo "=== Migration Complete ==="
echo "Secrets file: $SECRETS_FILE  (mode 0600, owner $(id -un))"
echo "Old .env backed up to: $BACKUP"
echo "Lines moved:"
printf '  %s\n' "$SECRET_LINES" | sed 's|=.*|=<redacted>|'
echo ""
echo "Next:"
echo "  1. docker compose up -d --force-recreate web celery"
echo "  2. docker compose exec web printenv MASTER_ENCRYPTION_KEY"
echo "     # should match the migrated value (not the placeholder)"
echo "  3. Read-test via flask shell or the UI."
echo ""
echo "After verifying the app works, shred the backup:"
echo "  shred -u $BACKUP"
