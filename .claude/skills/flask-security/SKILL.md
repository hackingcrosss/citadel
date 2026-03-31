---
name: flask-security
description: Security conventions for InfraRed Flask app. Auto-invoked when editing API endpoints, routes, services, or models to prevent common vulnerabilities.
user-invocable: false
paths:
  - "app/api/**/*.py"
  - "app/routes.py"
  - "app/services/**/*.py"
  - "app/models/**/*.py"
  - "app/utils/**/*.py"
  - "app/tasks/**/*.py"
---

# InfraRed Security Conventions

Apply these rules when writing or modifying backend Python code.

## Authentication & Authorization

1. **Every route must have `@login_required`** — no exceptions. Place it directly after the route decorator.
2. **Admin routes**: add `@admin_required` after `@login_required`.
3. **Feature-gated routes**: add `@feature_required('feature_name')` after `@login_required`.
4. **Project-scoped routes**: add `@project_member_required(write=True/False)` for endpoints that operate on project resources. Use `write=True` for any mutation (POST/PUT/DELETE).
5. **Never trust client-supplied IDs for authorization** — always verify the current user has access to the resource. Use `assert_domain_accessible()` for domains, `g.project` for project-scoped resources.

## Credential Handling

6. **Never store secrets in plaintext** — always use `credential_service.save_credential(provider, key, value, label)` and `credential_service.get_credential(provider, key, label)`.
7. **Never log decrypted credentials** — not even at DEBUG level.
8. **Never return decrypted credentials in API responses** unless the endpoint specifically exists for that purpose (e.g., settings page). When returning credential metadata, omit the value field.

## Input Validation

9. **Validate all user input at the API boundary**:
   - Use `request.get_json(silent=True)` and check for `None` before accessing fields.
   - Validate types, lengths, and formats before passing to services.
   - Hostnames: validate against RFC-1123 regex (`^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$`).
   - IDs from URL params: use Flask's `<int:id>` converter, never parse manually.

10. **Never use `eval()`, `exec()`, or `os.system()`** — use `subprocess.run()` with argument lists if shell commands are needed.

11. **Never use string formatting/concatenation for SQL** — SQLAlchemy ORM or `db.session.execute(text(...), params)` with bound parameters only.

12. **Never use `| safe` in Jinja templates** on user-supplied data. If you must render HTML, sanitize it server-side first with a whitelist-based sanitizer.

## API Response Patterns

13. **Error responses** must follow this format — never expose stack traces or internal details:
    ```python
    return jsonify({'error': 'Human-readable message'}), 4xx
    ```

14. **Plan-gated errors** must include the upgrade flag:
    ```python
    return jsonify({'error': '...', 'upgrade_required': True}), 402
    ```

15. **Never return database model objects directly** — always use `.to_dict()` or explicit field selection.

## Redirect & URL Safety

16. **Never redirect to user-supplied URLs without validation**. The existing pattern in `routes.py` validates `next` param:
    ```python
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        next_url = None  # reject absolute URLs
    ```
    Follow this pattern for any new redirect logic.

## File Operations

17. **Never write user-uploaded content to predictable paths** without sanitizing the filename with `werkzeug.utils.secure_filename()`.
18. **Never serve user-uploaded files directly** — always validate the file type and serve through a controlled endpoint.

## Celery Tasks

19. **Tasks must not access `current_user` or `request`** — pass user IDs and data as task arguments.
20. **Tasks must handle their own database sessions** — use the Flask app context pattern from `celery_app.py`.

## Multi-Account Provider Pattern

21. **All multi-account provider functions must accept a `label` parameter** (default `'default'`). Never hardcode a specific account label.
22. **Validate label exists** before using it — call `get_account_labels(provider)` and check membership.
