---
name: provider-integration
description: Add a new Citadel external provider integration using encrypted credentials, account labels, service functions, API endpoints, settings UI support, project scoping, and audit logging. Use when integrating a cloud, DNS, CDN, mail, scanner, phishing, or infrastructure provider.
argument-hint: "<provider name and capability>"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(rg *), Bash(git *), Bash(python *)
---

# Provider Integration

Use this to add a new provider or substantial new provider capability.

## Existing Provider Pattern

Provider logic lives in `app/services/<provider>_service.py` as plain functions. Credentials are read through:

```python
from app.services.credential_service import get_credential, get_account_labels
```

Multi-account providers accept `label='default'` and usually expose:

- `verify_credentials(label='default')`
- `list_* (label='default', ...)`
- `_fetch_*_for_account(lbl, ...)`
- `list_*_all_accounts(...)`

API modules live in `app/api/<provider>/__init__.py` and register routes on shared `api_bp`.

## Implementation Workflow

1. Inspect a similar provider first:
   - Cloud/compute: `aws_service.py`, `azure_service.py`, or `hetzner_service.py`.
   - DNS: `dns_service.py` or `azure_dns_service.py`.
   - CDN: `cdn_service.py`.
   - Tool API: `gophish_service.py`, `cobaltstrike_service.py`, or `npm_service.py`.
2. Define credential keys and labels.
3. Add service functions:
   - Keep provider SDK/API handling in the service.
   - Keep functions stateless.
   - Return normalized dicts for API/template use.
   - Do not leak raw SDK objects.
4. Add credential test support:
   - Service `verify_credentials(...)`.
   - `/api/credentials/<provider>/test` support if needed by the existing credentials API.
   - Settings template support if credentials need visible fields.
5. Add API endpoints:
   - Use `api_bp`, `@login_required`, RBAC decorators, project checks, and feature gates.
   - Validate request JSON and provider label.
   - Return consistent JSON errors.
6. Add page/template integration only if the user-facing workflow needs it.
7. Add project scoping:
   - Reads should respect active project when the resource is project-owned.
   - Mutations should block read-only roles and wrong-project resources.
   - Tag newly created resources to the active project when appropriate.
8. Add audit logs for provider mutations and credential/account changes.
9. Register new API modules in `app/api/__init__.py` and routes/templates in `app/routes.py` as needed.

## Credential Handling Rules

- Never hardcode provider secrets.
- Never log credentials or return them in API responses.
- Store secrets only through `credential_service.set_credential(...)`.
- Read secrets only through `get_credential(provider, key, label)`.
- Validate labels with `get_account_labels(provider)` for multi-account operations.

## Error Handling

- Catch expected SDK/API exceptions at API boundaries or service boundaries consistently with nearby providers.
- Return generic API errors to users.
- Preserve useful details in server logs only when they do not contain secrets.
- External mutations should be as idempotent as practical.

## Verification

- Run `python -m compileall app` if feasible.
- Test credential verification with missing, invalid, and valid credentials when possible.
- Test read-only roles and wrong-project access for mutating endpoints.
- If using a new dependency, update `requirements.txt` and deployment notes.

## Output

Report:

- Credential keys added.
- Service/API/template files changed.
- Auth/scoping rules.
- External operations implemented.
- Verification performed and any provider calls not tested.
