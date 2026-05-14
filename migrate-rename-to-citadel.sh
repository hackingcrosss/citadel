#!/usr/bin/env bash
# One-shot prod migration helper for the InfraRed → Citadel rename.
#
# Stops the old infrared-* container set, moves the external secrets file to
# the Citadel path, ALTERs the Postgres role + database to the new names,
# patches DATABASE_URL in the secrets file, and brings up the new stack.
#
# Idempotent: each step checks state and skips if already applied. Safe to
# re-run if a step fails partway through.
#
# Usage:
#     ./migrate-rename-to-citadel.sh
#
# Override the source/destination paths via env vars if you keep secrets
# somewhere non-default:
#     INFRARED_SECRETS_FILE=/etc/infrared/secrets.env \
#     CITADEL_SECRETS_FILE=/etc/citadel/secrets.env \
#     ./migrate-rename-to-citadel.sh

set -euo pipefail

OLD_SECRETS="${INFRARED_SECRETS_FILE:-}"
NEW_SECRETS="${CITADEL_SECRETS_FILE:-}"

# Pick a default pair that matches whichever location actually has the file.
if [[ -z "$OLD_SECRETS" && -z "$NEW_SECRETS" ]]; then
    for candidate in "/etc/infrared/secrets.env" "${HOME}/.config/infrared/secrets.env"; do
        if [[ -f "$candidate" ]]; then
            OLD_SECRETS="$candidate"
            NEW_SECRETS="${candidate/infrared/citadel}"
            break
        fi
    done
fi

# If we still didn't find one, assume already migrated and just look for the
# new location.
if [[ -z "$NEW_SECRETS" ]]; then
    for candidate in "/etc/citadel/secrets.env" "${HOME}/.config/citadel/secrets.env"; do
        if [[ -f "$candidate" ]]; then
            NEW_SECRETS="$candidate"
            break
        fi
    done
fi

if [[ -z "$NEW_SECRETS" ]]; then
    echo "ERROR: could not locate a secrets file at any standard path." >&2
    echo "Set INFRARED_SECRETS_FILE (current location) and/or CITADEL_SECRETS_FILE (target)." >&2
    exit 1
fi

echo "==> Plan:"
echo "    OLD_SECRETS=${OLD_SECRETS:-<none>}"
echo "    NEW_SECRETS=${NEW_SECRETS}"
echo ""

# ---------------------------------------------------------------------------
# Step 1 — stop the old infrared-* container set, if any are still running
# ---------------------------------------------------------------------------
if docker ps --format '{{.Names}}' | grep -q '^infrared-'; then
    echo "==> Step 1/5: stopping old infrared-* containers"
    docker ps --format '{{.Names}}' | grep '^infrared-' | xargs -r docker stop
else
    echo "==> Step 1/5: no infrared-* containers running (skip)"
fi

# ---------------------------------------------------------------------------
# Step 2 — move the secrets file to its Citadel path
# ---------------------------------------------------------------------------
if [[ -n "$OLD_SECRETS" && -f "$OLD_SECRETS" && ! -f "$NEW_SECRETS" ]]; then
    echo "==> Step 2/5: moving $OLD_SECRETS -> $NEW_SECRETS"
    mkdir -p "$(dirname "$NEW_SECRETS")"
    mv "$OLD_SECRETS" "$NEW_SECRETS"
    rmdir "$(dirname "$OLD_SECRETS")" 2>/dev/null || true
else
    echo "==> Step 2/5: secrets already at $NEW_SECRETS (skip)"
fi

# ---------------------------------------------------------------------------
# Step 3 — patch DATABASE_URL in the secrets file
# ---------------------------------------------------------------------------
if grep -qE 'postgresql://infrared:|@postgres:5432/infrared' "$NEW_SECRETS"; then
    echo "==> Step 3/5: patching DATABASE_URL inside $NEW_SECRETS"
    cp -p "$NEW_SECRETS" "$NEW_SECRETS.bak.$(date +%s)"
    sed -i 's|postgresql://infrared:|postgresql://citadel:|g; s|@postgres:5432/infrared|@postgres:5432/citadel|g' "$NEW_SECRETS"
else
    echo "==> Step 3/5: DATABASE_URL already targets citadel (skip)"
fi

# ---------------------------------------------------------------------------
# Step 4 — boot postgres alone, rename the role + database
# ---------------------------------------------------------------------------
export CITADEL_SECRETS_FILE="$NEW_SECRETS"

echo "==> Step 4/5: starting postgres-only for ALTER"
docker compose up -d postgres

# Wait for postgres
for i in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -q 2>/dev/null; then
        break
    fi
    sleep 1
done

# Local-socket trust auth (see M-13) lets us connect without a password to
# perform the rename. The role we're renaming cannot itself execute ALTER
# ROLE on its own name from an active session, so we connect as postgres
# bootstrap.
exec_psql_postgres() {
    docker compose exec -T postgres psql -U "$1" -d postgres -tA -c "$2"
}

renamed_role=0
if exec_psql_postgres infrared "SELECT 1 FROM pg_roles WHERE rolname='infrared';" 2>/dev/null | grep -q 1; then
    echo "    role 'infrared' present — renaming to 'citadel'"
    # Connect AS postgres OS user via local socket is not available here;
    # but the infrared role is a superuser per the entrypoint, so it can
    # rename a different role. We need a second superuser to rename it.
    # The simplest portable approach: create a temporary super, do the
    # rename, drop the temp.
    exec_psql_postgres infrared "CREATE ROLE _migrate_tmp WITH SUPERUSER LOGIN PASSWORD 'tmp-${RANDOM}${RANDOM}';" >/dev/null
    exec_psql_postgres _migrate_tmp "ALTER ROLE infrared RENAME TO citadel;" >/dev/null
    exec_psql_postgres citadel "DROP ROLE _migrate_tmp;" >/dev/null
    renamed_role=1
else
    echo "    role 'infrared' not found (already renamed?)"
fi

renamed_db=0
if exec_psql_postgres citadel "SELECT 1 FROM pg_database WHERE datname='infrared';" 2>/dev/null | grep -q 1; then
    echo "    database 'infrared' present — renaming to 'citadel'"
    exec_psql_postgres citadel "ALTER DATABASE infrared RENAME TO citadel;" >/dev/null
    renamed_db=1
else
    echo "    database 'infrared' not found (already renamed?)"
fi

if [[ $renamed_role -eq 0 && $renamed_db -eq 0 ]]; then
    echo "    nothing to ALTER — postgres already on citadel/citadel"
fi

# ---------------------------------------------------------------------------
# Step 5 — bring up the rest of the stack
# ---------------------------------------------------------------------------
echo "==> Step 5/5: bringing up full citadel stack"
docker compose up -d

echo ""
echo "==> Done."
echo ""
echo "Verify:"
echo "    docker compose exec postgres psql -U citadel -d citadel -c 'SELECT 1;'"
echo "    curl -sk -o /dev/null -w '%{http_code}\\n' https://localhost/"
echo ""
echo "If everything checks out you can delete the old infrared-* containers:"
echo "    docker rm \$(docker ps -a --format '{{.Names}}' | grep '^infrared-') 2>/dev/null"
