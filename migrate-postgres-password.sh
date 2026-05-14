#!/bin/bash
# One-shot migration: rotates the Postgres password on an existing deployment.
#
# - Reads the OLD password from .env's DATABASE_URL.
# - Generates a fresh POSTGRES_PASSWORD.
# - Stops web + celery to drain SQLAlchemy connection pools before the ALTER.
# - Runs `ALTER USER citadel WITH PASSWORD '<new>'` against the running
#   postgres container, authenticating with the OLD password.
# - Appends POSTGRES_PASSWORD + DATABASE_URL (with NEW password embedded) to
#   the secrets file.
# - Strips DATABASE_URL from .env.
#
# After running, the operator MUST:
#   docker compose up -d --force-recreate postgres web celery
#
# Idempotency: refuses to run if POSTGRES_PASSWORD is already in the secrets
# file. Pre-rotation .env is backed up.

set -euo pipefail

cd "$(dirname "$0")"

SECRETS_FILE="${CITADEL_SECRETS_FILE:-$HOME/.config/citadel/secrets.env}"

# --- Validation ---
if [ ! -f .env ]; then
    echo "[!] .env not found in $(pwd)" >&2
    exit 1
fi
if [ ! -f "$SECRETS_FILE" ]; then
    echo "[!] $SECRETS_FILE not found." >&2
    echo "    Run ./migrate-secrets-out-of-repo.sh first." >&2
    exit 1
fi
if grep -q '^POSTGRES_PASSWORD=' "$SECRETS_FILE"; then
    echo "[!] $SECRETS_FILE already contains POSTGRES_PASSWORD; refusing to clobber." >&2
    echo "    If you really want to re-rotate, remove these lines from $SECRETS_FILE:" >&2
    echo "      POSTGRES_PASSWORD / DATABASE_URL" >&2
    exit 1
fi

# --- Parse OLD password from .env DATABASE_URL ---
OLD_DATABASE_URL=$(grep '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)
if [ -z "$OLD_DATABASE_URL" ]; then
    echo "[!] DATABASE_URL not found in .env" >&2
    echo "    Expected line: DATABASE_URL=postgresql://citadel:<password>@postgres:5432/citadel" >&2
    exit 1
fi
OLD_PG_PASSWORD=$(echo "$OLD_DATABASE_URL" | sed -n 's|^postgresql://[^:]*:\([^@]*\)@.*$|\1|p')
if [ -z "$OLD_PG_PASSWORD" ]; then
    echo "[!] Could not parse password from .env DATABASE_URL" >&2
    echo "    Expected form: postgresql://user:password@host:port/db" >&2
    exit 1
fi
echo "[+] Parsed OLD Postgres password from .env DATABASE_URL"

# --- Confirm postgres is reachable ---
if ! docker compose exec -T postgres true >/dev/null 2>&1; then
    echo "[!] postgres container is not running or not reachable." >&2
    docker compose ps postgres >&2
    exit 1
fi

# --- Generate NEW password ---
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python  >/dev/null 2>&1; then PY=python
else
    echo "[!] python3 or python required" >&2
    exit 1
fi
NEW_PG_PASSWORD=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')
echo "[+] Generated NEW POSTGRES_PASSWORD"

# --- Stop web + celery to drain the connection pool ---
echo "[+] Stopping web + celery (avoids pool-recycle auth failures during ALTER)"
docker compose stop web celery

# --- ALTER USER on postgres (uses OLD password to authenticate) ---
echo "[+] ALTER USER citadel WITH PASSWORD <new>"
docker compose exec -T -e PGPASSWORD="$OLD_PG_PASSWORD" postgres \
    psql -U citadel -d citadel \
    -v ON_ERROR_STOP=1 \
    -c "ALTER USER citadel WITH PASSWORD '$NEW_PG_PASSWORD';" \
    > /dev/null
echo "[+] Postgres user password rotated"

# --- Update secrets file ---
echo "[+] Appending postgres entries to $SECRETS_FILE"
{
    echo "POSTGRES_PASSWORD=$NEW_PG_PASSWORD"
    echo "DATABASE_URL=postgresql://citadel:$NEW_PG_PASSWORD@postgres:5432/citadel"
} >> "$SECRETS_FILE"
chmod 0600 "$SECRETS_FILE"

# --- Strip DATABASE_URL from .env ---
BACKUP=.env.backup.pre-postgres-rotate.$(date +%Y%m%d-%H%M%S)
cp .env "$BACKUP"
sed -i '/^DATABASE_URL=/d' .env
echo "[+] .env backed up to $BACKUP and DATABASE_URL stripped"

echo ""
echo "=== Migration Complete ==="
echo "Secrets file: $SECRETS_FILE"
echo "Old .env backed up to: $BACKUP"
echo ""
echo "Next:"
echo "  1. docker compose up -d --force-recreate postgres web celery"
echo "     # postgres re-reads env_file (POSTGRES_PASSWORD env now matches the"
echo "     # in-DB password); web/celery pick up the new DATABASE_URL."
echo "  2. docker compose ps                    # all five Up, no restart loops"
echo "  3. docker compose exec -T -e PGPASSWORD=\"\$POSTGRES_PASSWORD\" postgres \\"
echo "       sh -c 'psql -U citadel -d citadel -c \"SELECT 1;\"'"
echo "     # Expected: 1"
echo "  4. docker compose exec web flask shell <<<'from app.services.credential_service import get_all_for_provider; print(list(get_all_for_provider(\"cloudflare\").keys()))'"
echo "     # Expected: provider labels, no decryption errors"
echo ""
echo "After verifying the app works:"
echo "  shred -u $BACKUP"
