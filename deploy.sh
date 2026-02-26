#!/usr/bin/env bash
# deploy.sh — sync InfraRed to a remote host and restart Docker services
#
# Usage:
#   ./deploy.sh
#   REMOTE_HOST=ops@10.0.0.5 ./deploy.sh
#
# First run: generates SECRET_KEY + MASTER_ENCRYPTION_KEY, writes .env on the
#            remote from .env.example, then builds and starts all containers.
# Subsequent runs: syncs changed files and restarts the stack. .env is never
#                  touched again.

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────
REMOTE_HOST="${REMOTE_HOST:-user@10.0.0.1}"
REMOTE_DIR="${REMOTE_DIR:-/opt/infrared}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
HTTP_PORT="${HTTP_PORT:-80}"
HTTPS_PORT="${HTTPS_PORT:-443}"

SSH_OPTS=(
  -i "$SSH_KEY"
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=10
)

RSYNC_EXCLUDES=(
  --exclude='.git/'
  --exclude='.env'          # never sync local secrets to remote
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='*.pyo'
  --exclude='.pytest_cache/'
  --exclude='*.egg-info/'
  --exclude='.DS_Store'
)
# ──────────────────────────────────────────────────────────────────────────────

# ─── Pre-flight: verify remote has docker compose (V2) ───────────────────────
echo "[0/4] Checking remote prerequisites"
ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" bash -s <<'PREFLIGHT'
if ! docker compose version &>/dev/null; then
  echo ""
  echo "ERROR: 'docker compose' (V2) not found on remote host."
  echo "Install it with:"
  echo "  sudo apt-get install -y docker-compose-plugin"
  echo "or follow: https://docs.docker.com/compose/install/"
  exit 1
fi
echo "    docker compose $(docker compose version --short) — OK"
PREFLIGHT

# ─── Step 1: sync files ───────────────────────────────────────────────────────
echo "[1/4] Syncing files → ${REMOTE_HOST}:${REMOTE_DIR}"
rsync -az --delete \
  "${RSYNC_EXCLUDES[@]}" \
  -e "ssh ${SSH_OPTS[*]}" \
  ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

# ─── Step 2: create .env if it doesn't exist on remote ───────────────────────
ENV_EXISTS=$(ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" \
  "[ -f '${REMOTE_DIR}/.env' ] && echo yes || echo no")

if [ "$ENV_EXISTS" = "no" ]; then
  echo "[2/4] Generating secrets and writing .env on remote"

  # Generate keys locally — python3 is always available in a Flask project
  secret_key=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  enc_key=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

  # Substitute placeholders in .env.example and pipe the result directly to
  # the remote — the keys never touch disk locally
  sed \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=\"${secret_key}\"|" \
    -e "s|^MASTER_ENCRYPTION_KEY=.*|MASTER_ENCRYPTION_KEY=\"${enc_key}\"|" \
    -e "s|^HTTP_PORT=.*|HTTP_PORT=${HTTP_PORT}|" \
    -e "s|^HTTPS_PORT=.*|HTTPS_PORT=${HTTPS_PORT}|" \
    .env.example \
  | ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" \
      "cat > '${REMOTE_DIR}/.env' && chmod 600 '${REMOTE_DIR}/.env'"

  echo "    .env written (HTTP=${HTTP_PORT}, HTTPS=${HTTPS_PORT})"
else
  echo "[2/4] .env already exists on remote — skipping"
fi

# ─── Step 3: build and start containers ──────────────────────────────────────
echo "[3/4] Building and starting containers"
ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" bash -s <<REMOTE
set -euo pipefail
cd "${REMOTE_DIR}"
chmod 700 .
docker compose up -d --build --remove-orphans
REMOTE

# ─── Step 4: status ───────────────────────────────────────────────────────────
echo "[4/4] Service status"
ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" \
  "cd '${REMOTE_DIR}' && docker compose ps"

echo ""
echo "Done. InfraRed is running on ${REMOTE_HOST}"
echo ""
echo "First time? Initialize the database with:"
echo "  ssh -i \$SSH_KEY ${REMOTE_HOST} \"cd ${REMOTE_DIR} && docker compose exec web python init_db.py\""
