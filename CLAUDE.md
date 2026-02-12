# InfraRed - Red Team Infrastructure Management Platform

## Project Overview
InfraRed is a Flask-based web application for managing red team infrastructure. It provides a centralized dashboard to manage domains, Docker containers, AWS EC2 instances, and Nginx Proxy Manager entries with encrypted credential storage.

## Tech Stack
- **Backend**: Flask (Python 3.11)
- **Database**: PostgreSQL 15
- **Task Queue**: Celery + Redis
- **Frontend**: Bootstrap 5, vanilla JavaScript
- **Containerization**: Docker + Docker Compose V2
- **Proxy**: Nginx

## Project Structure
```
infrared/
├── docker-compose.yml          # Multi-container orchestration
├── Dockerfile                  # Web application container
├── requirements.txt            # Python dependencies
├── .env                        # Environment variables (not in git)
├── .env.example               # Template for environment setup
├── init_db.py                 # Database initialization script
├── README.md                  # User documentation
├── TROUBLESHOOTING.md         # Debug guide
├── app/
│   ├── __init__.py           # Flask app factory
│   ├── routes.py             # Application routes
│   ├── config/
│   │   └── __init__.py       # Configuration classes
│   ├── models/
│   │   ├── __init__.py
│   │   └── user.py           # User authentication model
│   ├── services/             # Business logic (DNS, Docker, AWS, etc.)
│   ├── tasks/                # Celery async tasks
│   ├── api/                  # REST API endpoints
│   │   ├── __init__.py
│   │   ├── domains/
│   │   ├── containers/
│   │   ├── aws/
│   │   ├── npm/
│   │   ├── email/
│   │   ├── gophish/
│   │   ├── cobaltstrike/
│   │   └── credentials/
│   ├── templates/            # Jinja2 HTML templates
│   │   ├── base.html         # Base template with sidebar
│   │   ├── login.html        # Login page
│   │   ├── change_password.html  # Password change form
│   │   ├── dashboard.html    # Main dashboard
│   │   ├── domains.html      # Domain management
│   │   ├── containers.html   # Container management
│   │   ├── email.html        # Mailgun email management
│   │   ├── aws.html          # AWS EC2 management
│   │   ├── npm.html          # Nginx Proxy Manager
│   │   ├── operations.html   # Cross-service orchestration
│   │   ├── gophish.html      # GoPhish sending profiles
│   │   ├── cobaltstrike.html # Cobalt Strike listener management
│   │   └── settings.html     # API credentials config
│   └── static/               # CSS, JS, images
├── docker/
│   ├── nginx/
│   │   └── nginx.conf        # Reverse proxy config
│   ├── postgres/
│   └── redis/
└── tests/
```

## Docker Services
```yaml
services:
  postgres:    # Database (port 5432)
  redis:       # Task queue broker (port 6379)
  web:         # Flask app (port 5000)
  celery:      # Background workers
  nginx:       # Reverse proxy (ports 80, 443)
```

## Key Features Implemented

### Authentication & Security
- Flask-Login for session management
- Password hashing with Werkzeug
- Forced password change on first login (default: admin@infrared.local / admin)
- `must_change_password` flag on User model
- Encrypted credential storage using Fernet (AES-256)
- Master encryption key in environment variables

### User Flow
1. Login with default credentials
2. Forced redirect to change password
3. Password validation (min 8 chars, must differ from current)
4. Access dashboard after password change

### Pages & Routes
- `/` - Redirect to dashboard or login
- `/login` - Authentication (GET/POST)
- `/logout` - Session termination
- `/change-password` - Forced password change (GET/POST)
- `/dashboard` - Main overview (EC2, containers, domains)
- `/domains` - Domain management interface
- `/containers` - Docker container management
- `/email` - Mailgun domain and SMTP credential management
- `/aws` - AWS EC2 instance management
- `/npm` - Nginx Proxy Manager host management
- `/operations` - Cross-service orchestration (email setup, DNS pointing, reverse proxy, GoPhish integration)
- `/gophish` - GoPhish sending profile management
- `/cobaltstrike` - Cobalt Strike listener management
- `/settings` - API credential configuration
- `/api/*` - REST endpoints for all services

## Database Models

### User Model
```python
class User(UserMixin, db.Model):
    id: int (primary key)
    email: str (unique, indexed)
    password_hash: str
    display_name: str
    is_active: bool (default=True)
    is_admin: bool (default=False)
    must_change_password: bool (default=True)
    created_at: datetime
    last_login: datetime
```

## Environment Variables
```bash
# Flask
FLASK_APP=app
FLASK_ENV=development
SECRET_KEY=<64-char-hex>
MASTER_ENCRYPTION_KEY=<base64-fernet-key>

# Database
DATABASE_URL=postgresql://infrared:infrared_password@postgres:5432/infrared

# Redis/Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# API Keys (encrypted in DB after first setup)
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
# CLOUDFLARE_API_TOKEN=
# MAILGUN_API_KEY=
# NPM_API_URL=
# NPM_API_TOKEN=
```

## Setup Commands
```bash
# Generate keys
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python -c "import secrets; print(secrets.token_hex(32))"

# Setup
cp .env.example .env
# Edit .env with generated keys

# Start services
docker compose up -d --build

# Initialize database
docker compose exec web python init_db.py

# Access at http://localhost
# Login: admin@infrared.local / admin (will force password change)
```

## Development Commands
```bash
# View logs
docker compose logs -f web
docker compose logs -f celery

# Restart services
docker compose restart web
docker compose restart celery

# Shell access
docker compose exec web bash
docker compose exec web python  # Python REPL with app context

# Database migrations
docker compose exec web flask db migrate -m "description"
docker compose exec web flask db upgrade

# Rebuild after code changes
docker compose up -d --build

# Stop everything
docker compose down

# Reset database
docker compose down -v
docker volume rm infrared_postgres_data
docker compose up -d --build
docker compose exec web python init_db.py
```

## Important Notes

### Docker Compose V2
- Always use `docker compose` (space, not hyphen)
- This is the newer syntax and what the project uses

### File Creation Order
1. Run setup script to create all files
2. Copy files to project directory
3. Edit `.env` with encryption keys
4. Build and start containers
5. Initialize database

### Security Considerations
- Never commit `.env` to git
- Change default admin password immediately
- Master encryption key must be 32-byte base64 Fernet key
- All API credentials encrypted before database storage
- Use HTTPS in production (configure nginx SSL)

## Implemented Services

### Backend Services (all complete)
- `app/services/dns_service.py` - Cloudflare DNS management (zones, records, SSL)
- `app/services/docker_service.py` - Docker SDK (list, start/stop/restart/remove, logs, stats, remote host support, network IPs in listing)
- `app/services/aws_service.py` - boto3 EC2 management (instances, security groups, key pairs, multi-region)
- `app/services/email_service.py` - Mailgun integration (domains, SMTP credentials, multi-region)
- `app/services/npm_service.py` - Nginx Proxy Manager API (proxy hosts, certificates, redirections)
- `app/services/gophish_service.py` - GoPhish API (sending profiles CRUD, connection verification)
- `app/services/cobaltstrike_service.py` - Cobalt Strike REST API (JWT auth with token caching, listener CRUD)
- `app/services/credential_service.py` - Fernet encryption/decryption for all stored credentials

### API Endpoints (all complete)
- `/api/credentials` - Credential CRUD + test for all providers, single credential GET (aws, cloudflare, mailgun, npm, docker, gophish, cobaltstrike)
- `/api/domains` - Cloudflare zone and DNS record management
- `/api/containers` - Docker container management (list, details, start/stop/restart/remove, logs, stats)
- `/api/aws` - EC2 instance management (list, details, start/stop/reboot/terminate, security groups, key pairs)
- `/api/npm` - Nginx Proxy Manager proxy hosts, certificates, redirections
- `/api/email` - Mailgun domain and SMTP credential management
- `/api/gophish` - GoPhish sending profile management (list, create, delete)
- `/api/cobaltstrike` - Cobalt Strike listener management (list, create, delete with type-aware validation)

### Frontend (all complete)
- Dashboard with live data from all services, auto-refresh every 30 seconds
- Containers page with logs viewer, detail inspector, status/name filters, auto-refresh
- AWS EC2 page with instance detail/security group modals, bulk actions, status/name filters
- Domains page with zone selector, DNS record editor, SSL settings
- Email page with domain management, DNS verification, SMTP credentials
- NPM page with proxy host management
- Operations page with cross-service orchestration: email domain setup (region-aware) with GoPhish integration (auto-creates Mailgun SMTP credential + GoPhish sending profile), unified Point Domain card (EC2 direct or Service via NPM with container picker)
- GoPhish page with sending profile table (view, create via modal, delete)
- Cobalt Strike page with listener table and dynamic create modal (fields adapt per listener type: HTTP, HTTPS, DNS, SMB, TCP, Foreign)
- Settings page with credential management for all providers including Docker remote host, NPM public IP (with EC2 instance picker), GoPhish API credentials, and Cobalt Strike teamserver credentials

## Next Steps (To Be Implemented)

### Celery Tasks
- `app/tasks/celery_app.py` - Celery instance configuration
- `app/tasks/dns_tasks.py` - Async DNS updates
- `app/tasks/container_tasks.py` - Async container deployment

### Database Models (To Add)
- Domain model (name, registrar, dns_records, email_status)
- DNSRecord model (domain_id, type, value)

## Common Issues & Solutions

### Login 500 Error
1. Check logs: `docker compose logs web`
2. Verify database initialized: `docker compose exec web python init_db.py`
3. Check User model imported: `docker compose exec web python -c "from app.models.user import User; print(User)"`

### Database Connection Failed
1. Check postgres running: `docker compose ps`
2. Test connection: `docker compose exec postgres psql -U infrared -d infrared -c "SELECT 1;"`
3. Check DATABASE_URL in `.env`

### Image Missing Files
- Rebuild: `docker compose up -d --build`
- Files added after initial build won't be in container

See TROUBLESHOOTING.md for complete debug guide.

## Color Scheme
- Primary: #dc2626 (red)
- Dark: #991b1b (dark red)
- Background: Linear gradient #1f2937 to #111827
- Sidebar: Dark gradient with red accents

## Default Credentials
- Email: admin@infrared.local
- Password: admin (must change on first login)