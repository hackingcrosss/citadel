---
name: citadel-arch
description: Citadel architecture knowledge — file map, models, API patterns, service patterns, design tokens. Auto-loaded to reduce token usage from repeated codebase exploration.
user-invocable: false
---

# Citadel Architecture Quick Reference

Use this as your primary reference before reading files. Only read source when you need exact implementation details.

## Stack
Flask 3 + SQLAlchemy + PostgreSQL 15 + Celery/Redis + Bootstrap 5 + vanilla JS. Docker Compose V2 (`docker compose`, not `docker-compose`). Python 3.11.

## File Map

### Core
- `app/__init__.py` — Flask app factory, registers blueprints + login manager
- `app/routes.py` — All page routes (`@login_required`, some `@admin_required` / `@feature_required`)
- `app/config/__init__.py` — Config classes (reads env vars)
- `app/utils/decorators.py` — `admin_required`, `feature_required(name)`, `project_member_required(write=bool)`

### Models (`app/models/`)
| Model | Table | Key Fields |
|-------|-------|------------|
| `User` | `users` | email, password_hash, role(`admin`/`operator`/`viewer`/`white_team`/`auditor`), plan_override, must_change_password |
| `Credential` | `credentials` | provider, key_name, label(`default`), encrypted_value. Unique on (provider, key_name, label) |
| `Domain` | `domains` | name, cloudflare_zone_id, credential_label, status, purpose, checked_out_by_project_id |
| `DNSRecord` | `dns_records` | domain_id(FK), cloudflare_record_id, record_type, name, content, managed_by |
| `License` | `licenses` | tier(`community`/`professional`/`team`/`enterprise`), org_name, custom limits |
| `Project` | `projects` | code, name, description, status, created_by_id |
| `ProjectMember` | `project_members` | project_id, user_id, role(`project_admin`/`operator`/`white_team`) |
| `ProjectResource` | `project_resources` | project_id, resource_type, resource_id, tagged_by_id |
| `InstanceTag` | `instance_tags` | instance_id, tag |
| `InstanceSSHConfig` | `instance_ssh_configs` | provider, instance_id, ssh_username, encrypted_private_key |
| `DomainGroomingTag` | `domain_grooming_tags` | domain_id, tag |
| `EmailGroomingConfig` | `email_grooming_configs` | domain_id, project_id, provider config fields |

### Services (`app/services/`)
All services are stateless modules with plain functions (no classes). They read credentials via `credential_service.get_credential(provider, key, label)`.

| Service | Purpose |
|---------|---------|
| `dns_service` | Cloudflare zones/records/SSL, multi-account via `list_zones_all_accounts()` |
| `aws_service` | boto3 EC2, multi-account via `list_instances_all_accounts(region)` |
| `docker_service` | Docker SDK — list, start/stop/restart/remove, logs, stats |
| `email_service` | Mailgun domains + SMTP creds, multi-region (us/eu) |
| `npm_service` | Nginx Proxy Manager API — proxy hosts, certs, redirections |
| `gophish_service` | GoPhish sending profiles |
| `cobaltstrike_service` | CS REST API v1, per-label JWT cache, listener CRUD |
| `credential_service` | Fernet encrypt/decrypt, `get_account_labels()`, `delete_account()` |
| `website_generator_service` | Azure OpenAI website gen + Docker deploy + NPM + CF DNS |
| `plan_service` | License tier defs, `get_current_plan()`, feature/limit checks |
| `project_service` | Project CRUD, membership, resource tagging, domain checkout |
| `audit_service` | Audit trail logging |
| `ssh_service` | EC2 SSH via stored keys |
| `task_log_service` | In-memory/Redis task tracking |

### API Endpoints (`app/api/<module>/__init__.py`)
All blueprints register on `api_bp` (prefix `/api`). Pattern:
```python
from app.api import api_bp

@api_bp.route('/resource', methods=['GET'])
@login_required
def list_resource():
    return jsonify(result)
```
- Success: return JSON with 200
- Client error: `jsonify({'error': 'msg'}), 4xx`
- Plan-gated: `jsonify({'error': '...', 'upgrade_required': True}), 402`
- Multi-account providers (`aws`, `cloudflare`, `azure`, `cobaltstrike`): accept `?label=` param

### Templates (`app/templates/`)
- Extend `base.html` via `{% extends "base.html" %}`
- Block: `{% block title %}`, `{% block content %}`
- All action templates inject JS role constants at top of `<script>`:
```javascript
const IS_AUDITOR = {{ 'true' if current_user.role == 'auditor' else 'false' }};
const IS_WHITE_TEAM = {{ 'true' if current_user.role == 'white_team' else 'false' }};
const IS_READONLY = IS_AUDITOR || IS_WHITE_TEAM;
const ACTIVE_PROJECT_ID = {{ active_project.id if active_project else 'null' }};
const ACTIVE_PROJECT_CODE = {{ active_project.code | tojson if active_project else 'null' }};
```
- Write actions gated with `if (!IS_READONLY) { ... }`
- Fetch pattern: `fetch('/api/...').then(r => r.json()).then(data => { ... })`

### Static (`app/static/`)
CSS and JS files. No build step — plain files served directly.

## Design Tokens (from `base.html :root`)
```css
--ir-red: #f05252;       --ir-red-dim: rgba(240,82,82,0.15);
--ir-bg: #0d1117;        --ir-surface: #161b22;    --ir-surface-2: #1c2128;
--ir-border: rgba(255,255,255,0.07);  --ir-border-2: rgba(255,255,255,0.12);
--ir-text: #e6edf3;      --ir-text-muted: #7d8590; --ir-text-dim: #484f58;
--ir-green: #3fb950;     --ir-yellow: #d29922;      --ir-blue: #58a6ff;
--ir-orange: #f0883e;    --sidebar-width: 240px;    --topbar-h: 48px;
```

## Roles & Access
| Role | Page Access | API Write | Project Scope |
|------|-------------|-----------|---------------|
| `admin` | All | All | Bypasses project checks |
| `operator` | Non-admin pages | Own project resources | Scoped to project membership |
| `viewer` | Read-only pages | None | N/A |
| `white_team` | Project pages (read) | None | Read-only on assigned projects |
| `auditor` | All pages (read) | None | Read-only on all projects |

## Plan Tiers
| Tier | Users | Domains | Features |
|------|-------|---------|----------|
| community | 1 | 3 | Base |
| professional | 5 | 20 | + gophish, website_gen |
| team | 20 | unlimited | + cobaltstrike, infra_map, projects |
| enterprise | unlimited | unlimited | All |
Admins always get enterprise access regardless of license.
