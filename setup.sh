#!/bin/bash
# InfraRed Setup Script

set -e

echo "=== InfraRed Infrastructure Setup ==="

echo "[+] Generating MASTER_ENCRYPTION_KEY"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

echo "[+] Generating SECRET_KEY key"
python -c "import secrets; print(secrets.token_hex(32))"

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "1. cd infrared"
echo "2. cp .env.example .env"
echo "3. Edit .env and set your MASTER_ENCRYPTION_KEY and SECRET_KEY to the previously generated keys"
echo "4. Run: docker-compose up -d"
echo ""