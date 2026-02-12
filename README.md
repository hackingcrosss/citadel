# InfraRed - Red Team Infrastructure Management

A web application for managing red team infrastructure including domains, Docker containers, AWS EC2 instances, and Nginx Proxy Manager entries.

## Features

- **Dashboard**: Live overview pulling real-time data from all integrated services, auto-refreshing every 30 seconds
- **Domain Management**: Cloudflare DNS zone and record management, SSL settings
- **Container Management**: Docker container listing, start/stop/restart, logs, and resource stats via local Docker socket
- **AWS EC2 Monitoring**: Multi-region instance management, security groups, key pairs, start/stop/reboot/terminate
- **Nginx Proxy Manager**: Proxy host CRUD, enable/disable, certificates, redirections
- **Email (Mailgun)**: Domain management, DNS verification, SMTP credential management, multi-region support
- **Secure Credential Storage**: All API keys encrypted with Fernet (AES-256) before database storage

## Quick Start

### 1. Generate Encryption Keys

```bash
# Generate master encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Generate Flask secret key
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set:
- `MASTER_ENCRYPTION_KEY` - Use the Fernet key from step 1
- `SECRET_KEY` - Use the hex key from step 1

### 3. Start Services

```bash
docker compose up -d --build
```

### 4. Initialize Database

```bash
docker compose exec web python init_db.py
```

### 5. Access Application

Open http://localhost in your browser

**Default Credentials:**
- Email: `admin@infrared.local`
- Password: `admin`

You will be forced to change the password on first login.

## Architecture

```
Browser  -->  Nginx (80/443)  -->  Flask/Gunicorn (5000)
                                      |
                              +-------+-------+
                              |               |
                          PostgreSQL       Redis
                           (5432)         (6379)
                              |               |
                          DB models      Celery broker
```

### Tech Stack
- **Backend**: Flask 3.0 (Python 3.11)
- **Database**: PostgreSQL 15
- **Task Queue**: Celery 5.3 + Redis 7
- **Frontend**: Bootstrap 5.3, vanilla JavaScript
- **Containerization**: Docker Compose V2
- **Proxy**: Nginx

### Docker Services

| Service    | Image             | Port  | Purpose                    |
|------------|-------------------|-------|----------------------------|
| `postgres` | postgres:15-alpine| 5432  | Database                   |
| `redis`    | redis:7-alpine    | 6379  | Task queue broker          |
| `web`      | Custom Dockerfile | 5000  | Flask application          |
| `celery`   | Custom Dockerfile | -     | Background workers         |
| `nginx`    | nginx:alpine      | 80,443| Reverse proxy              |

The `web` container mounts `/var/run/docker.sock` for direct Docker container management.

## Services & API Endpoints

### Credentials (`/api/credentials`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/credentials/<provider>` | Get credentials for provider (masked) |
| POST   | `/api/credentials/<provider>` | Save credentials |
| POST   | `/api/credentials/<provider>/test` | Test credentials |
| DELETE | `/api/credentials/<provider>/<key_name>` | Delete credential |

### AWS EC2 (`/api/aws`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/aws/instances` | List instances (optional `?region=`) |
| GET    | `/api/aws/instances/<id>` | Instance details |
| POST   | `/api/aws/instances/start` | Start instances |
| POST   | `/api/aws/instances/stop` | Stop instances |
| POST   | `/api/aws/instances/reboot` | Reboot instances |
| POST   | `/api/aws/instances/terminate` | Terminate instances |
| GET    | `/api/aws/security-groups` | List security groups |
| GET    | `/api/aws/security-groups/<id>` | Security group details |
| GET    | `/api/aws/key-pairs` | List key pairs |
| GET    | `/api/aws/regions` | List available regions |

### Domains / Cloudflare (`/api/domains`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/domains/zones` | List zones |
| GET    | `/api/domains/zones/<id>` | Zone details |
| GET    | `/api/domains/zones/<id>/records` | List DNS records |
| POST   | `/api/domains/zones/<id>/records` | Create DNS record |
| PUT    | `/api/domains/zones/<id>/records/<rid>` | Update DNS record |
| DELETE | `/api/domains/zones/<id>/records/<rid>` | Delete DNS record |
| GET    | `/api/domains/zones/<id>/ssl` | Get SSL setting |
| PATCH  | `/api/domains/zones/<id>/ssl` | Set SSL mode |

### Containers / Docker (`/api/containers`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/containers` | List all containers (optional `?all=false` for running only) |
| GET    | `/api/containers/<id>` | Container details |
| POST   | `/api/containers/<id>/start` | Start container |
| POST   | `/api/containers/<id>/stop` | Stop container |
| POST   | `/api/containers/<id>/restart` | Restart container |
| GET    | `/api/containers/<id>/logs` | Container logs (optional `?tail=100`) |
| GET    | `/api/containers/<id>/stats` | Container CPU/memory stats |

### Nginx Proxy Manager (`/api/npm`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/npm/hosts` | List proxy hosts |
| POST   | `/api/npm/hosts` | Create proxy host |
| GET    | `/api/npm/hosts/<id>` | Get proxy host |
| PUT    | `/api/npm/hosts/<id>` | Update proxy host |
| DELETE | `/api/npm/hosts/<id>` | Delete proxy host |
| POST   | `/api/npm/hosts/<id>/enable` | Enable proxy host |
| POST   | `/api/npm/hosts/<id>/disable` | Disable proxy host |
| GET    | `/api/npm/certificates` | List certificates |
| GET    | `/api/npm/redirections` | List redirection hosts |
| POST   | `/api/npm/token` | Authenticate and store token |

### Email / Mailgun (`/api/email`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/email/domains` | List domains (optional `?region=`) |
| POST   | `/api/email/domains` | Add domain |
| GET    | `/api/email/domains/<name>` | Domain details + DNS records |
| DELETE | `/api/email/domains/<name>` | Delete domain |
| POST   | `/api/email/domains/<name>/verify` | Verify domain DNS |
| GET    | `/api/email/domains/<name>/credentials` | List SMTP credentials |
| POST   | `/api/email/domains/<name>/credentials` | Create SMTP credential |
| DELETE | `/api/email/domains/<name>/credentials/<login>` | Delete SMTP credential |

## Dashboard

The dashboard fetches live data from all services on page load and auto-refreshes every 30 seconds:

- **Stat cards**: Active Cloudflare zones, running Docker containers, running EC2 instances, NPM proxy hosts
- **EC2 table**: Top 5 instances with name, type, region, and state
- **Containers table**: Top 5 containers with name, image, port, and state
- **Cloudflare Zones table**: All zones with domain, status, name servers, and plan

Each section loads independently. If a service's credentials aren't configured, that section shows a "Not configured" message with a link to Settings. Other sections continue to work normally.

## Configuration

API credentials are configured in the Settings page (`/settings`):
- **AWS**: Access Key ID, Secret Access Key, Default Region
- **Cloudflare**: API Token
- **Mailgun**: API Key
- **NPM**: API URL, API Token (or authenticate via email/password)

All credentials are encrypted with Fernet (AES-256) before being stored in the database.

## Development

### View Logs
```bash
docker compose logs -f web
docker compose logs -f celery
```

### Restart Services
```bash
docker compose restart web
docker compose restart celery
```

### Rebuild After Code Changes
```bash
docker compose up -d --build
```

### Shell Access
```bash
docker compose exec web bash
docker compose exec web python  # Python REPL with app context
```

### Database Migrations
```bash
docker compose exec web flask db migrate -m "description"
docker compose exec web flask db upgrade
```

### Stop / Reset
```bash
# Stop everything
docker compose down

# Full reset (destroys data)
docker compose down -v
docker compose up -d --build
docker compose exec web python init_db.py
```

## Security

- All API credentials encrypted at rest using Fernet (AES-256)
- Master encryption key stored as environment variable
- Password hashing with Werkzeug (PBKDF2)
- Flask sessions secured with secret key
- All API endpoints require authentication (`@login_required`)
- Forced password change on first login
- Docker socket access scoped to the web container only
- HTTPS recommended for production (configure nginx with SSL certificates)

## Production Deployment

1. Use strong, unique encryption keys
2. Configure HTTPS/SSL certificates in nginx
3. Change default admin password immediately
4. Set up firewall rules (restrict ports 5432, 6379, 5000 to internal only)
5. Regular backups of PostgreSQL database
6. Monitor logs for security issues
7. Consider restricting Docker socket access

## License

For red team operations only. Use responsibly and with proper authorization.
