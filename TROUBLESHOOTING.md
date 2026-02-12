# InfraRed - Troubleshooting Guide

## Bad Gateway (502)

Nginx is running but the Flask app isn't responding.

```bash
# Check if the web container is running
docker compose ps

# Check web container logs for errors
docker compose logs --tail 50 web

# Restart nginx
docker compose restart nginx

# If web container is crashing, rebuild
docker compose up -d --build
```

## Login Internal Server Error

### 1. Check the logs
```bash
docker compose logs -f web
```

### 2. Common Issues & Solutions

#### Issue: "User model not found" or "models have no attribute"
```bash
docker compose exec web python -c "from app.models.user import User; print(User.query.all())"
```

#### Issue: "No module named 'app.models.user'"
Ensure `__init__.py` exists in the models directory:
```bash
docker compose exec web ls -la app/models/
```

#### Issue: Database table doesn't exist
```bash
docker compose exec web python init_db.py
```

#### Issue: SECRET_KEY not set
Check your `.env` file has `SECRET_KEY` set:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
# Add the output to .env as SECRET_KEY=<value>
```

#### Issue: Database connection error
```bash
docker compose ps
# postgres should show "Up"

docker compose exec postgres psql -U infrared -d infrared -c "SELECT 1;"
```

### 3. Complete Reset

```bash
docker compose down -v
docker compose up -d --build
sleep 10
docker compose exec web python init_db.py
```

### 4. Verify Setup

```bash
docker compose exec web python -c "
from app import create_app, db
from app.models.user import User
app = create_app()
with app.app_context():
    user = User.query.filter_by(email='admin@infrared.local').first()
    print(f'User found: {user}')
    print(f'Password check: {user.check_password(\"admin\")}')
"
```

## Password Reset

If you've lost access to the admin account, reset the password directly:

```bash
docker compose exec web python -c "
from app import create_app, db
from app.models.user import User
from werkzeug.security import generate_password_hash

app = create_app()
with app.app_context():
    user = User.query.filter_by(email='admin@infrared.local').first()
    user.password_hash = generate_password_hash('admin')
    user.must_change_password = True
    db.session.commit()
    print('Password reset to: admin')
"
```

This only resets the password. API credentials stored in the database are not affected.

## Password Change Flow

1. Login with `admin@infrared.local` / `admin`
2. Automatically redirected to `/change-password`
3. Enter current password: `admin`
4. Enter new password (minimum 8 characters, must differ from current)
5. Confirm new password
6. Redirected to dashboard

## Dashboard Shows "Not Configured"

The dashboard fetches live data from each service independently. If a section shows "Not configured" or `!`, the credentials for that service haven't been set up.

1. Go to **Settings** (`/settings`)
2. Enter credentials for the relevant provider (AWS, Cloudflare, Mailgun, NPM)
3. Click **Test Connection** to verify
4. Return to the dashboard — data should populate on the next refresh (or click Refresh)

### Section-specific issues

**EC2 Instances — "Failed to load - check AWS credentials"**
- Verify AWS Access Key ID and Secret Access Key in Settings
- Check the configured default region has instances
- Test with: `docker compose exec web python -c "from app.services.aws_service import verify_credentials; print(verify_credentials())"`

**Containers — "Failed to connect to Docker"**

For local Docker socket:
- Check docker-compose.yml mounts the socket:
  ```yaml
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
  ```
- Check socket permissions: `ls -la /var/run/docker.sock`

For remote Docker host:
- Verify the Docker Host URL is set in Settings (e.g. `tcp://remote:2375`)
- If using an SSH tunnel, make sure it's running and bound to `0.0.0.0` (not just localhost):
  ```bash
  ssh -nNT -L 0.0.0.0:2375:localhost:2375 user@remote-host
  ```
- The `web` service needs `extra_hosts` in docker-compose.yml:
  ```yaml
  extra_hosts:
    - "host.docker.internal:host-gateway"
  ```
- Test with: `docker compose exec web python -c "from app.services.docker_service import list_containers; print(len(list_containers()), 'containers')"`

**Cloudflare Zones — "Failed to load - check Cloudflare credentials"**
- Verify API Token in Settings
- Token needs Zone:Read permission at minimum
- Test with: `docker compose exec web python -c "from app.services.dns_service import verify_token; print(verify_token())"`

**NPM Entries — "Not configured"**
- Set the NPM API URL (e.g., `http://npm-host:81/api`) and API Token in Settings
- Or use the NPM login form in Settings to authenticate with email/password
- Test with: `docker compose exec web python -c "from app.services.npm_service import verify_connection; print(verify_connection())"`

**Mailgun — no dashboard section but used by email page**
- Configure API Key in Settings
- Test with: `docker compose exec web python -c "from app.services.email_service import verify_api_key; print(verify_api_key())"`

## Remote Docker Daemon Won't Start

### "Start request repeated too quickly"
The `hosts` setting in `/etc/docker/daemon.json` conflicts with the `-H fd://` flag in the systemd unit file.

Fix: remove the `-H fd://` from the main unit file:
```bash
sudo sed -i 's|ExecStart=/usr/bin/dockerd.*|ExecStart=/usr/bin/dockerd|' /usr/lib/systemd/system/docker.service
sudo systemctl daemon-reload
sudo systemctl restart docker
```

### "Service has more than one ExecStart= setting"
A systemd drop-in override file has a duplicate `ExecStart`. Either fix the override or delete it and edit the main unit file directly:
```bash
sudo rm -rf /etc/systemd/system/docker.service.d/
sudo systemctl daemon-reload
sudo systemctl restart docker
```

### Verify remote Docker is listening
```bash
# On the remote host
curl http://localhost:2375/version
sudo ss -tlnp | grep 2375
```

## Docker Socket Permission Denied

If the container API returns a permission error when listing containers:

```bash
# Check socket permissions on host
ls -la /var/run/docker.sock

# If needed, make it accessible (development only)
sudo chmod 666 /var/run/docker.sock
```

In production, add the container user to the docker group or use a Docker socket proxy.

## Container Stats Fail for Stopped Containers

`GET /api/containers/<id>/stats` only works for running containers. The Docker API does not provide stats for stopped containers. This is expected behavior — the dashboard table does not call stats, it only lists containers.

## Encryption Key Issues

#### MASTER_ENCRYPTION_KEY not set or invalid
```
ValueError: Fernet key must be 32 url-safe base64-encoded bytes
```

Generate a valid key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add it to `.env` as `MASTER_ENCRYPTION_KEY=<value>` and restart:
```bash
docker compose restart web celery
```

#### Credentials saved with a different key
If you change `MASTER_ENCRYPTION_KEY` after saving credentials, existing encrypted values cannot be decrypted. You'll need to re-enter all API credentials in Settings.

## Flask Debug Mode

Enable detailed error messages temporarily:

Add to `.env`:
```env
FLASK_ENV=development
FLASK_DEBUG=1
```

Restart:
```bash
docker compose restart web
```

This shows full tracebacks in the browser. Disable in production.

## Service Won't Start

```bash
# Check all container statuses
docker compose ps

# If a container keeps restarting, check its logs
docker compose logs --tail 100 <service>

# Force rebuild from scratch
docker compose down
docker compose up -d --build
```

## Database Migrations

If models have changed and the database is out of sync:

```bash
docker compose exec web flask db migrate -m "description"
docker compose exec web flask db upgrade
```

If migrations are broken beyond repair:
```bash
docker compose down -v
docker compose up -d --build
docker compose exec web python init_db.py
```

This destroys all data including saved credentials.
