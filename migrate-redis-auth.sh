#!/bin/bash
# One-shot migration: enables Redis AUTH on an existing Citadel deployment.
#
# - Generates a fresh REDIS_PASSWORD.
# - Appends REDIS_PASSWORD / REDIS_URL / CELERY_BROKER_URL / CELERY_RESULT_BACKEND
#   (with password embedded) to the secrets file.
# - Strips REDIS_URL / CELERY_BROKER_URL / CELERY_RESULT_BACKEND from .env.
#
# Aborts if the secrets file already contains REDIS_PASSWORD. The original .env
# is backed up before any line is stripped.
#
# After running, the operator MUST:
#   docker compose up -d --force-recreate redis web celery
# Force-recreate is required because env_file values only re-load at container
# creation; `docker compose restart` keeps the old environment.

set -euo pipefail

cd "$(dirname "$0")"

SECRETS_FILE="${CITADEL_SECRETS_FILE:-$HOME/.config/citadel/secrets.env}"

if [ ! -f .env ]; then
    echo "[!] .env not found in $(pwd)" >&2
    exit 1
fi

if [ ! -f "$SECRETS_FILE" ]; then
    echo "[!] $SECRETS_FILE not found." >&2
    echo "    Run ./migrate-secrets-out-of-repo.sh first to create the secrets file." >&2
    exit 1
fi

if grep -q '^REDIS_PASSWORD=' "$SECRETS_FILE"; then
    echo "[!] $SECRETS_FILE already contains REDIS_PASSWORD; refusing to clobber." >&2
    echo "    If you really want to re-rotate, remove these lines from $SECRETS_FILE:" >&2
    echo "      REDIS_PASSWORD / REDIS_URL / CELERY_BROKER_URL / CELERY_RESULT_BACKEND" >&2
    exit 1
fi

if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python  >/dev/null 2>&1; then PY=python
else
    echo "[!] python3 or python required to generate the password" >&2
    exit 1
fi

echo "[+] Generating REDIS_PASSWORD"
REDIS_PASSWORD=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')

echo "[+] Appending redis entries to $SECRETS_FILE"
{
    echo "REDIS_PASSWORD=$REDIS_PASSWORD"
    echo "REDIS_URL=redis://:$REDIS_PASSWORD@redis:6379/0"
    echo "CELERY_BROKER_URL=redis://:$REDIS_PASSWORD@redis:6379/0"
    echo "CELERY_RESULT_BACKEND=redis://:$REDIS_PASSWORD@redis:6379/0"
} >> "$SECRETS_FILE"
chmod 0600 "$SECRETS_FILE"

BACKUP=.env.backup.pre-redis-auth.$(date +%Y%m%d-%H%M%S)
cp .env "$BACKUP"
sed -i '/^REDIS_URL=/d; /^CELERY_BROKER_URL=/d; /^CELERY_RESULT_BACKEND=/d' .env

echo ""
echo "=== Migration Complete ==="
echo "Secrets file: $SECRETS_FILE"
echo "Old .env backed up to: $BACKUP"
echo ""
echo "Next:"
echo "  1. docker compose up -d --force-recreate redis web celery"
echo "  2. docker compose exec redis sh -c 'redis-cli ping; redis-cli -a \"\$REDIS_PASSWORD\" ping'"
echo "     # Expected: NOAUTH... then PONG"
echo "  3. docker compose ps          # all four Up, no restart loops"
echo "  4. docker compose logs web --tail=20"
echo ""
echo "After verifying the app works (login, credential reads, celery task):"
echo "  shred -u $BACKUP"
