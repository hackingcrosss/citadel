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

## Operations Page Issues

### "Add to Mailgun" button is disabled
The page automatically checks if the domain already exists in Mailgun when you select a zone, change the subdomain, or change the region. The check uses the domain+region combination, so switching from US to EU will re-check. If the domain is found, "Add to Mailgun" is disabled and "Push DNS to Cloudflare" is enabled — skip straight to pushing DNS records.

### Domain not found in wrong region
Mailgun US and EU are separate environments. A domain added in US won't be found when checking EU, and vice versa. Make sure the region selector matches where the domain was originally added.

### No DNS records returned after adding to Mailgun
The Operations page does a separate `GET /api/email/domains/{name}` after creating the domain to fetch DNS records. Mailgun returns `sending_dns_records` (SPF, DKIM) and `receiving_dns_records` (MX) at the root level of the response. If no records appear:
1. Check the Mailgun API key is valid in Settings
2. Verify the domain was actually created: go to the Email page and check the domain list
3. Try clicking "Push DNS to Cloudflare" — it will attempt to re-fetch records from Mailgun

### DNS records fail to push to Cloudflare
- "Already exists" warnings are expected if records were previously created — the workflow continues with remaining records
- Other errors typically mean the Cloudflare API token lacks write permissions for the zone
- Verify the token has `Zone:DNS:Edit` permission

### Verify step shows "unverified" after pushing DNS
DNS propagation can take minutes to hours. Wait and retry the "Verify Domain" button later. Mailgun checks propagation on their side.

### "NPM Public IP not configured" warning
The "Service (via NPM reverse proxy)" target mode requires the NPM host's public IP to create the DNS A record. Set it in **Settings** → NPM section → "Public IP" field. You can select an EC2 instance from the dropdown to auto-fill its IP.

### Container dropdown is empty
The container dropdown only shows running containers (`?all=false`). If no containers are running or Docker credentials aren't configured, the dropdown will be empty. Enter the forward host and port manually instead.

### "Add to GoPhish" button stays disabled
The button is only enabled when all sending DNS records (SPF, DKIM) are verified by Mailgun. This means:
1. The domain must exist in Mailgun
2. DNS records must be pushed to Cloudflare
3. The domain must pass Mailgun verification (all sending records show "valid")

If records show "not verified", wait for DNS propagation and click "Verify Domain" again. After successful verification, the page re-fetches domain data and enables the button if all sending records are now valid.

### "Add to GoPhish" fails at SMTP credential step
- Check that the Mailgun API key in Settings has write permissions
- The SMTP login format is `username@domain` — the username field should be just the local part (e.g., `postmaster`, not `postmaster@domain.com`)
- If the credential already exists in Mailgun, the API will return an error

### "Add to GoPhish" fails at sending profile step
- Verify GoPhish credentials are configured in Settings (API URL and API Key)
- Test the GoPhish connection in Settings first
- The GoPhish API URL should include the scheme (e.g., `https://gophish.example.com:3333`)
- The API key is the one shown in GoPhish's admin panel under Settings

### Point Domain creates A record but proxy fails
The workflow creates the A record first, then the NPM proxy host. If the proxy step fails (e.g. NPM credentials not configured), the A record will still exist. Fix the NPM credentials in Settings and retry — the "already exists" warning for the A record is handled gracefully.

## GoPhish Page Issues

### "GoPhish credentials not configured"
Configure the GoPhish API URL and API Key in **Settings** → GoPhish section. The API URL should include the port if non-standard (e.g., `https://gophish.example.com:3333`). The API Key is found in GoPhish admin panel under Settings.

### Sending profiles not loading
- Verify the GoPhish instance is reachable from the InfraRed server
- GoPhish uses self-signed certificates by default — the service layer disables SSL verification (`verify=False`)
- Test with: `docker compose exec web python -c "from app.services.gophish_service import verify_connection; print(verify_connection())"`

### Creating a sending profile fails
The GoPhish API requires: `name`, `host` (with port, e.g., `smtp.mailgun.org:587`), `from_address`, `username`, `password`. The `interface_type` is set to `"SMTP"` automatically. Check that all fields are filled in the create modal.

## Cobalt Strike Page Issues

### "Cobalt Strike credentials not configured"
Configure the Teamserver URL, username, and password in **Settings** → Cobalt Strike section. The URL should include the scheme and port (e.g., `https://teamserver:50443`). The REST API runs on port 50443 by default (CS 4.12+).

### Authentication fails
- Verify the username and password are correct for the teamserver
- The REST API uses JWT authentication — the service authenticates automatically and caches the token
- If the token expires, the service re-authenticates on the next request (401 retry)
- Ensure the teamserver was started with REST API support enabled

### Listeners not loading
- Verify the teamserver is reachable from the InfraRed server on port 50443
- CS teamservers use self-signed certificates — the service disables SSL verification
- Test with: `docker compose exec web python -c "from app.services.cobaltstrike_service import verify_connection; print(verify_connection())"`

### Creating a listener fails
- The required fields depend on the listener type:
  - **HTTP/HTTPS**: name, host, port
  - **DNS**: name, host, port
  - **SMB**: name, pipename
  - **TCP**: name, host, port
  - **Foreign**: name, host, port
- Check that the teamserver doesn't already have a listener with the same name or port
- Verify the port is not in use on the teamserver

### Dynamic form fields don't appear
Select a listener type from the dropdown — the form fields are generated dynamically based on the selected type. If the dropdown shows "Select type..." no fields will appear.

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
