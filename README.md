# InfraRed - Red Team Infrastructure Management

A web application for managing red team infrastructure including domains, Docker containers, AWS EC2 instances, Nginx Proxy Manager, GoPhish, and Cobalt Strike — all from a single authenticated dashboard.

---

## Hardware Requirements

### Minimum
| Resource | Requirement |
|----------|-------------|
| CPU      | 1 vCPU / 1 core |
| RAM      | 1 GB |
| Disk     | 15 GB (Docker images ~2 GB + DB + logs) |
| Network  | Internet access (Cloudflare, AWS, Mailgun APIs) |

The minimum spec will run all five Docker services (nginx, web, celery, postgres, redis) under light, single-user load. Expect ~400–600 MB RAM in use at steady state.

### Recommended
| Resource | Requirement |
|----------|-------------|
| CPU      | 2 vCPUs / 2 cores |
| RAM      | 2 GB |
| Disk     | 30 GB SSD |
| Network  | Stable broadband (low-latency API calls improve UX) |

The recommended spec provides comfortable headroom for multiple concurrent users, larger DNS zone syncs, and database growth over an engagement lifecycle.

> **Note:** These figures cover InfraRed itself. They do not account for Cobalt Strike, GoPhish, or any other red team tooling you run on the same host.

---

## Features

- **Dashboard**: Live overview of all integrated services, auto-refreshing every 30 seconds
- **Domain Management**: Cloudflare DNS zone and record management, SSL settings, bulk multi-select delete
- **Container Management**: Docker container listing, start/stop/restart/remove, logs viewer, detail inspector, status/name filtering. Supports local socket or remote Docker host via TCP/TLS
- **AWS EC2 Monitoring**: Multi-region instance management, security groups, key pairs, start/stop/reboot/terminate, status/name/tag filtering, local instance tagging (stored in local DB)
- **Nginx Proxy Manager**: Proxy host CRUD, enable/disable, certificates, redirections
- **Email (Mailgun)**: Domain management, DNS verification, SMTP credential management, multi-region (US/EU)
- **GoPhish**: Sending profile management — view, create, and delete SMTP sending profiles
- **Cobalt Strike**: Listener management — view, create (HTTP, HTTPS, DNS, SMB, TCP, Foreign, ExternalC2, UserDefinedC2), and delete listeners via the CS REST API (4.12+) with JWT authentication
- **Setup** (Operations): Cross-service orchestration — set up email domains (Mailgun + Cloudflare DNS), push SMTP credentials to GoPhish, point domains to EC2 instances or containers via NPM, deploy full C2 infrastructure (CS listener + NPM proxy + Cloudflare DNS) in one workflow
- **C2 Deployments**: Two-tab view — *C2 Deployments* (active listeners cross-referenced with NPM and DNS, teardown with real-time log) and *Groomed Sites* (deployed phishing/redirect websites with container and domain info, deletable)
- **Infrastructure Map**: Visual overview of the full infrastructure chain — domains, DNS records, EC2 instances, NPM proxies, containers, and CS listeners — in both table and interactive diagram form
- **Website Generator**: AI-generated (Azure OpenAI) single-page websites for a given business category with optional design instructions; live preview with brand summary (colors, style, tagline); publish directly to Docker + NPM + Cloudflare in one step; runs as a background Celery task, resumable across page loads
- **Domain Farming**: Queue website generation per domain/subdomain, publish to Docker + NPM + Cloudflare; deployed sites visible on the Groomed Sites tab of the Deployments page
- **Secure Credential Storage**: All API keys encrypted with Fernet (AES-256) before database storage

---

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
- `MASTER_ENCRYPTION_KEY` — Fernet key from step 1
- `SECRET_KEY` — hex key from step 1

### 3. Start Services

```bash
docker compose up -d --build
```

### 4. Initialize Database

```bash
docker compose exec web python init_db.py
```

### 5. Access Application

Open http://localhost in your browser.

**Default Credentials:**
- Email: `admin@infrared.local`
- Password: `admin`

You will be forced to change the password on first login.

---

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
- **Frontend**: Bootstrap 5.3, vanilla JavaScript, vis-network 9.1.9 (diagram)
- **Containerization**: Docker Compose V2
- **Proxy**: Nginx

### Docker Services

| Service    | Image              | Port    | Purpose                   |
|------------|--------------------|---------|---------------------------|
| `postgres` | postgres:15-alpine | 5432    | Database                  |
| `redis`    | redis:7-alpine     | 6379    | Task queue broker         |
| `web`      | Custom Dockerfile  | 5000    | Flask application         |
| `celery`   | Custom Dockerfile  | —       | Background workers        |
| `nginx`    | nginx:alpine       | 80, 443 | Reverse proxy             |

The `web` container mounts `/var/run/docker.sock` for direct Docker container management.

---

## Services & API Endpoints

### Credentials (`/api/credentials`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/credentials/<provider>` | Get credentials for provider (masked) |
| GET    | `/api/credentials/<provider>/<key>` | Get single credential (unmasked) |
| POST   | `/api/credentials/<provider>` | Save credentials |
| POST   | `/api/credentials/<provider>/test` | Test credentials |
| DELETE | `/api/credentials/<provider>/<key>` | Delete credential |

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
| GET    | `/api/aws/tags` | List local tags (or `?instance_id=` for one instance) |
| POST   | `/api/aws/tags` | Add a local tag to an instance |
| DELETE | `/api/aws/tags` | Remove a local tag from an instance |

### Domains / Cloudflare (`/api/domains`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/domains` | List locally tracked domains |
| POST   | `/api/domains` | Track a new domain locally |
| GET    | `/api/domains/<id>` | Get local domain with DNS records |
| PUT    | `/api/domains/<id>` | Update local domain metadata |
| DELETE | `/api/domains/<id>` | Remove domain from local tracking |
| POST   | `/api/domains/<id>/sync` | Sync DNS records from Cloudflare into local DB |
| GET    | `/api/domains/zones` | List Cloudflare zones |
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
| GET    | `/api/containers` | List all containers (optional `?all=false`) |
| GET    | `/api/containers/<id>` | Container details |
| POST   | `/api/containers/<id>/start` | Start container |
| POST   | `/api/containers/<id>/stop` | Stop container |
| POST   | `/api/containers/<id>/restart` | Restart container |
| DELETE | `/api/containers/<id>` | Remove container (optional `?force=true`) |
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
| POST   | `/api/npm/token` | Authenticate and store NPM token |

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

### GoPhish (`/api/gophish`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/gophish/profiles` | List sending profiles |
| GET    | `/api/gophish/profiles/<id>` | Get sending profile |
| POST   | `/api/gophish/profiles` | Create sending profile |
| DELETE | `/api/gophish/profiles/<id>` | Delete sending profile |

### Cobalt Strike (`/api/cobaltstrike`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/cobaltstrike/listeners` | List listeners |
| GET    | `/api/cobaltstrike/listeners/<id>` | Get listener details |
| POST   | `/api/cobaltstrike/listeners` | Create listener (type-aware validation) |
| DELETE | `/api/cobaltstrike/listeners/<id>` | Stop and delete listener |

### Website Generator (`/api/website-generator`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | `/api/website-generator/generate` | Start background generation task (returns `task_id`) |
| GET    | `/api/website-generator/status/<task_id>` | Poll Celery task status |
| POST   | `/api/website-generator/deploy` | Deploy generated HTML to a new Docker container |
| POST   | `/api/website-generator/relaunch` | Relaunch all website containers |
| POST   | `/api/website-generator/publish` | Full publish flow: deploy container + configure NPM + create Cloudflare DNS |
| GET    | `/api/website-generator/deployed-sites` | List deployed sites (from docker-compose + NPM matching) |
| DELETE | `/api/website-generator/deployed-sites/<folder_name>` | Stop container and remove its service |

### Task Log (`/api/task-log`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/task-log` | List all tracked background tasks |
| DELETE | `/api/task-log/completed` | Clear all completed/failed tasks from the log |
| POST   | `/api/task-log/<task_id>/revoke` | Cancel a pending or running Celery task |

---

## Page Reference

### Dashboard (`/dashboard`)
Live overview pulling real-time data from all services; auto-refreshes every 30 seconds.
- Stat cards: active Cloudflare zones, running containers, running EC2 instances, NPM proxy hosts
- EC2 table: top 5 instances with name, type, region, and state
- Containers table: top 5 containers with name, image, ports, and state
- Cloudflare zones table: all zones with domain, status, name servers, and plan

Each section loads independently — if a service isn't configured it shows a "Not configured" message while the rest of the page continues to work.

### Domains (`/domains`)
- Zone selector loads all Cloudflare zones
- Filter records by type (A, AAAA, CNAME, MX, TXT)
- Zone info bar: status, SSL mode (editable), name servers, plan
- Add, edit, and delete individual DNS records
- **Bulk delete**: checkbox column with header toggle, Select All button, and Delete Selected (N) button — deletes selected records sequentially via the Cloudflare API

### Containers (`/containers`)
- Live list of all Docker containers with name, image, ports, status, and creation time
- Stat cards: running, stopped, restarting, total counts
- Actions: start, stop, restart, remove (force option for running containers)
- Logs viewer modal with configurable tail count (50/100/500/1000 lines)
- Detail inspector showing full container config
- Frontend filters: status dropdown and name search
- Auto-refreshes every 15 seconds

### AWS EC2 (`/aws`)
- Multi-region instance listing with region selector
- Stat cards: total, running, stopped, other counts
- Single and bulk actions: start, stop, reboot, terminate (with confirmation)
- Instance detail modal: full metadata, security groups, tags
- Security group drill-down showing inbound/outbound rules
- **Local instance tagging**: add/remove tags per instance (stored in local DB, not AWS); shown as inline badges
- Frontend filters: status dropdown, name/ID search, tag filter dropdown
- Services tab: shows running services on each instance (requires SSH key configured in Settings)

### Setup (`/operations`)
Domain-centric cross-service orchestration. Zone selector drives all workflows on the page.

- **Setup Email Domain**: add a domain to Mailgun, push all DNS records to Cloudflare, verify with Mailgun, then push Mailgun SMTP credentials to GoPhish as a sending profile — all in one sequential flow with a live step log
- **Point Domain**: create a Cloudflare A record pointing to an EC2 instance directly, or to the NPM host's public IP with an NPM reverse proxy forwarding to a container or custom target
- **C2 Setup**: create a CS listener, create an NPM proxy host forwarding to the CS listener, and create Cloudflare DNS records pointing to RedWarden — modal-based with per-type field adaptation
- **Website Generator**: generate a realistic, AI-powered (Azure OpenAI) single-page site for a given business category; optionally specify a subdomain, extra design instructions (color scheme, tone, content focus); runs as a background Celery task with resume support; displays a live brand summary (color palette, tagline, style) and an iframe preview on completion; one-click **Publish** deploys the site to a Docker container, creates an NPM reverse proxy, and adds the Cloudflare DNS A record

### C2 Deployments (`/orchestration`)
Two-tab page for monitoring and tearing down active infrastructure.

**C2 Deployments tab**
- Lists active deployments by cross-referencing CS listeners with NPM proxy hosts and Cloudflare DNS records
- Shows listener name, type, stager host, bind port, callback hosts, NPM proxy entries, and resolved DNS A records
- **Inspect**: JSON detail modal for the full deployment object
- **Teardown**: deletes the CS listener, NPM proxy hosts, and DNS records with a confirmation dialog and real-time progress log

**Groomed Sites tab**
- Lists all deployed phishing/redirect websites published via the Website Generator
- Shows domain, category, container name, and folder
- **Delete**: stops the container, removes its service from docker-compose, and cleans up the site

### GoPhish (`/gophish`)
- Table of all sending profiles (SMTP name, host, from address)
- Create new profile via modal
- Delete individual profiles

### Cobalt Strike (`/cobaltstrike`)
- Table of all configured listeners
- Dynamic create modal: fields adapt per listener type (HTTP, HTTPS, DNS, SMB, TCP, ForeignHTTP, ForeignHTTPS, ExternalC2, UserDefinedC2)
- Host fields auto-populate from the configured CS Listener IP (set in Settings)
- Delete listeners (removes from teamserver)

### Infrastructure Map (`/infra-map`)

Visualises the full infrastructure chain across all managed services.

#### Table View
Four tables showing different perspectives of the same data:

| Table | What it shows |
|-------|---------------|
| **Infrastructure Chain** | Every tracked DNS record/NPM host grouped by Cloudflare zone, linked left-to-right: FQDN → DNS type → IP → EC2 → NPM proxy → Backend (container or CS listener badge) |
| **EC2 Without DNS Records** | EC2 instances whose public/private IP isn't found in any tracked DNS A record. Name filter (live, substring match) to narrow results. Also shows whether the instance is a forward target in any NPM host |
| **NPM Proxy Hosts Without Matching DNS** | NPM hosts whose domain names don't match any tracked zone |
| **DNS Records Pointing to NPM Without a Proxy Entry** | DNS A records whose IP matches the NPM host server but have no corresponding NPM proxy entry — useful for finding dangling records. Supports **bulk delete**: per-row checkboxes, header toggle, Select All button, Delete Selected (N) button |

#### Diagram View
Interactive hierarchical graph (left → right, 5 levels: Zone → FQDN → EC2 → NPM → Backend):
- Nodes are colour-coded by type (see legend below the diagram)
- **Click a node** to filter the diagram to only show the path passing through that node (all upstream and downstream connections highlighted, everything else dimmed)
- Click the same node again, or click empty space, to reset to the full diagram
- Scroll to zoom, drag to pan, Fit button to auto-fit all nodes

#### Sync DB
The **Sync DB** button opens a modal that:
1. Fetches all Cloudflare zones
2. Ensures each zone is tracked in the local database (creates missing entries automatically)
3. Runs `POST /api/domains/<id>/sync` for each zone, which pulls live DNS records from Cloudflare and removes stale entries from the local DB
4. Shows live progress with colour-coded status lines
5. Refreshes the infra map on completion

> NPM proxy hosts are fetched live and are not stored in InfraRed's database. To remove stale NPM entries, delete them directly from the [NPM page](/npm).

### Settings (`/settings`)
Configure API credentials for all integrated services:
- **AWS**: Access Key ID, Secret Access Key, Default Region
- **Cloudflare**: API Token
- **Mailgun**: API Key
- **NPM**: API URL, API Token (or authenticate via email/password), Public IP
- **GoPhish**: API URL, API Key
- **Cobalt Strike**: Teamserver URL, Username, Password, Listener IP (private IP of the teamserver EC2, used to auto-populate listener host fields)
- **RedWarden**: IP address (beacon reverse proxy, used in C2 Setup DNS records)
- **Docker**: Remote host URL and optional TLS certificates

All credentials are encrypted with Fernet (AES-256) before storage.

---

## Configuration

### Remote Docker Host

By default the app manages containers on the local Docker socket. To manage a remote host:

**Option 1: Expose Docker TCP**

Edit `/etc/docker/daemon.json` on the remote host:
```json
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2375"]
}
```

If using systemd, remove the `-H fd://` flag from the Docker unit file:
```bash
sudo sed -i 's|ExecStart=/usr/bin/dockerd.*|ExecStart=/usr/bin/dockerd|' \
    /usr/lib/systemd/system/docker.service
sudo systemctl daemon-reload && sudo systemctl restart docker
```

Set Docker Host URL in Settings to `tcp://<remote-ip>:2375`. For TLS (port 2376), paste CA + client certificates in Settings.

**Option 2: SSH Tunnel**

```bash
ssh -nNT -L 0.0.0.0:2375:localhost:2375 user@remote-host
```

Add to the `web` service in `docker-compose.yml`:
```yaml
services:
  web:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Set Docker Host URL in Settings to `tcp://host.docker.internal:2375`.

---

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
docker compose exec web python   # Python REPL with app context
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

# Full reset (destroys all data)
docker compose down -v
docker compose up -d --build
docker compose exec web python init_db.py
```

---

## Security

- All API credentials encrypted at rest (Fernet AES-256)
- Master encryption key stored as environment variable, never in the DB
- Password hashing with Werkzeug (PBKDF2)
- Flask sessions secured with secret key
- All routes and API endpoints require authentication (`@login_required`)
- Forced password change on first login
- Docker socket access scoped to the `web` container only
- HTTPS strongly recommended for production (configure nginx with SSL certificates)

## Production Deployment

1. Generate strong, unique `SECRET_KEY` and `MASTER_ENCRYPTION_KEY` values
2. Configure HTTPS/SSL certificates in nginx
3. Change default admin password immediately after first login
4. Restrict external access: ports 5432, 6379, and 5000 must not be exposed to the internet
5. Set up regular backups of the PostgreSQL volume
6. Monitor `docker compose logs` for errors
7. Consider placing the host behind a VPN or IP allowlist

---

## License

For authorised red team operations only. Use responsibly and only against infrastructure you have explicit permission to test.
