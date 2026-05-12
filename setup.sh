#!/bin/bash
# InfraRed Setup Script
# Generates a per-deployment .env from .env.example with freshly-generated
# SECRET_KEY and MASTER_ENCRYPTION_KEY values. Idempotent — preserves an
# existing .env so re-runs never overwrite live keys.

set -euo pipefail

cd "$(dirname "$0")"

echo "=== InfraRed Infrastructure Setup ==="

if [ -f .env ]; then
    echo "[!] .env already exists; leaving it untouched."
    echo "    To regenerate from scratch, move it aside first: mv .env .env.old"
    exit 0
fi

if [ ! -f .env.example ]; then
    echo "[!] .env.example missing; cannot template a fresh .env." >&2
    exit 1
fi

# Pick whichever Python is available; both have the secrets / cryptography stdlib.
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python  >/dev/null 2>&1; then PY=python
else
    echo "[!] python3 or python required to generate keys" >&2
    exit 1
fi

echo "[+] Generating SECRET_KEY"
SECRET_KEY=$("$PY" -c 'import secrets; print(secrets.token_hex(32))')

echo "[+] Generating MASTER_ENCRYPTION_KEY"
MASTER_ENCRYPTION_KEY=$("$PY" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')

# Write .env from .env.example, substituting the two placeholders.
sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" \
    -e "s|^MASTER_ENCRYPTION_KEY=.*|MASTER_ENCRYPTION_KEY=$MASTER_ENCRYPTION_KEY|" \
    .env.example > .env
chmod 600 .env

# Refuse to leave behind a half-templated file.
if grep -q 'CHANGE_ME' .env; then
    echo "[!] .env still contains CHANGE_ME placeholders after templating:" >&2
    grep -n CHANGE_ME .env >&2
    echo "    Edit those values manually before starting the stack." >&2
    exit 1
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Fresh secrets written to .env (mode 0600)."
echo "Next steps:"
echo "  1. docker compose up -d"
echo "  2. docker compose exec web flask db upgrade"
echo "  3. Create the initial admin user per README.md"
echo ""
