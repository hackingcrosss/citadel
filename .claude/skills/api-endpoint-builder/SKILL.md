---
name: api-endpoint-builder
description: Build new Citadel Flask API endpoints using the local api_bp pattern, authentication, RBAC, feature gating, input validation, JSON error contracts, audit logging, and project scoping. Use when adding or extending app/api modules.
argument-hint: "<endpoint description>"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(rg *), Bash(git *)
---

# API Endpoint Builder

Use this for new or expanded endpoints under `app/api/`.

## Existing Pattern

API modules import the shared blueprint:

```python
from app.api import api_bp
```

Routes are mounted under `/api` by `app/__init__.py`.

## Workflow

1. Read the closest existing API module for the feature area.
2. Read the matching service module. Keep business logic in `app/services/`; keep routes thin.
3. Add or update routes on `api_bp`.
4. Always add `@login_required` unless the endpoint is intentionally public.
5. Add the narrowest authorization:
   - Admin-only: `@admin_required`.
   - Plan-gated: `@feature_required('feature_name')`.
   - Project route with `project_id`: `@project_member_required(write=True/False)`.
   - Active-project resource route: use `project_service` checks.
6. Validate `request.get_json(silent=True)` and required fields before calling services.
7. Return JSON consistently:
   - Success: `jsonify(data)` or `jsonify({'ok': True, ...})`.
   - Client error: `jsonify({'error': 'message'}), 400/403/404`.
   - Plan-gated errors are handled by `feature_required`.
8. Never return model objects directly. Use `.to_dict()` or explicit response dicts.
9. Add audit logs for sensitive writes with `audit_service.log(...)`.
10. Import the module from `app/api/__init__.py` if it is new.

## Security Requirements

- Do not log secrets, tokens, private keys, or encrypted values.
- Do not return `password_hash`, `encrypted_*`, API keys, private keys, or raw provider credentials.
- Validate provider `label` against configured account labels when relevant.
- External provider mutations should catch expected service errors and return a generic API error.
- Use POST/PATCH/PUT/DELETE for state changes; never mutate on GET.

## Template Fetch Contract

Most templates use:

```javascript
fetch('/api/...')
  .then(r => r.json())
  .then(data => { ... })
```

When changing response shape, update the template code in the same change.

## Verification

At minimum:

- Run `python -m compileall app` if feasible.
- Exercise the endpoint manually or with `curl` when the app is running.
- Check that unauthenticated, read-only, and wrong-project callers fail as expected when applicable.

## Output

Report endpoint paths, authorization rules, response shape, and verification performed.
