#!/bin/bash
# InfraRed Setup Script
#
# Generates a per-deployment configuration on first install:
#   .env             — non-secret config (templated from .env.example)
#   $INFRARED_SECRETS_FILE
#                    — SECRET_KEY + MASTER_ENCRYPTION_KEY, stored OUTSIDE the
#                      repo so secrets never land in source control.
#                      Defaults to $HOME/.config/infrared/secrets.env (user-owned,
#                      XDG-style, no sudo). Override by exporting
#                      INFRARED_SECRETS_FILE before running.
#
# Idempotent: never overwrites an existing .env or secrets file. Re-run safely.

set -euo pipefail

cd "$(dirname "$0")"

SECRETS_FILE="${INFRARED_SECRETS_FILE:-$HOME/.config/infrared/secrets.env}"

echo "=== InfraRed Infrastructure Setup ==="
echo "Secrets file path: $SECRETS_FILE"
echo ""

# Pick whichever Python is available.
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python  >/dev/null 2>&1; then PY=python
else
    echo "[!] python3 or python required to generate keys" >&2
    exit 1
fi

# ----- Secrets file -----
if [ -f "$SECRETS_FILE" ]; then
    echo "[!] $SECRETS_FILE already exists; leaving it untouched."
else
    echo "[+] Generating SECRET_KEY, MASTER_ENCRYPTION_KEY, REDIS_PASSWORD"
    SECRET_KEY=$("$PY" -c 'import secrets; print(secrets.token_hex(32))')
    MASTER_ENCRYPTION_KEY=$("$PY" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
    REDIS_PASSWORD=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')

    SECRETS_DIR=$(dirname "$SECRETS_FILE")

    # Try to create without sudo first; if that fails, escalate.
    if mkdir -p "$SECRETS_DIR" 2>/dev/null && touch "$SECRETS_FILE" 2>/dev/null; then
        SUDO=""
    else
        echo "[+] $SECRETS_DIR requires elevated permissions; using sudo"
        SUDO="sudo"
        $SUDO mkdir -p "$SECRETS_DIR"
        $SUDO touch "$SECRETS_FILE"
    fi

    {
        echo "SECRET_KEY=$SECRET_KEY"
        echo "MASTER_ENCRYPTION_KEY=$MASTER_ENCRYPTION_KEY"
        echo "REDIS_PASSWORD=$REDIS_PASSWORD"
        echo "REDIS_URL=redis://:$REDIS_PASSWORD@redis:6379/0"
        echo "CELERY_BROKER_URL=redis://:$REDIS_PASSWORD@redis:6379/0"
        echo "CELERY_RESULT_BACKEND=redis://:$REDIS_PASSWORD@redis:6379/0"
    } | $SUDO tee "$SECRETS_FILE" > /dev/null
    $SUDO chmod 0600 "$SECRETS_FILE"
    $SUDO chown "$(id -u):$(id -g)" "$SECRETS_FILE"
    echo "[+] Wrote $SECRETS_FILE (mode 0600, owner $(id -un))"
fi

# ----- Non-secret .env -----
if [ -f .env ]; then
    echo "[!] .env already exists; leaving it untouched."
else
    if [ ! -f .env.example ]; then
        echo "[!] .env.example missing; cannot template a fresh .env." >&2
        exit 1
    fi
    cp .env.example .env
    # Defensive sweep: never leave SECRET_KEY/MASTER_ENCRYPTION_KEY placeholders
    # inside .env — they belong only in the secrets file.
    sed -i '/^SECRET_KEY=/d; /^MASTER_ENCRYPTION_KEY=/d; /^MASTER_ENCRYPTION_KEY_LEGACY=/d; /^REDIS_PASSWORD=/d; /^REDIS_URL=/d; /^CELERY_BROKER_URL=/d; /^CELERY_RESULT_BACKEND=/d' .env
    chmod 600 .env
    echo "[+] Wrote .env from .env.example (secrets stripped, mode 0600)"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. docker compose up -d"
echo "  2. docker compose exec web flask db upgrade"
echo "  3. Create the initial admin user per README.md"
echo ""
