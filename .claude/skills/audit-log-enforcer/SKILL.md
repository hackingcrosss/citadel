---
name: audit-log-enforcer
description: Add or review InfraRed audit logging for sensitive writes and infrastructure mutations. Use when changes touch credentials, users, roles, projects, companies, domains, provider actions, campaign launches, landing page deploys, checkout/tagging, or admin settings.
argument-hint: "[files or action]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(rg *), Bash(git *)
---

# Audit Log Enforcer

Use this to ensure meaningful write actions are recorded in `audit_logs`.

## Read First

- `app/services/audit_service.py`
- Nearby API modules that already call `audit_service.log(...)`
- `app/models/audit_log.py`

## Events That Should Be Audited

- Credential create/update/delete/test where useful.
- User create/update/disable/delete, role changes, plan override changes.
- License/plan changes.
- Project/company create/update/archive, member changes.
- Domain add/update/delete/sync, checkout/release, grooming tag changes.
- DNS, cloud, CDN, Docker, NPM, GoPhish, Cobalt Strike, Mailgun, Azure, Hetzner mutations.
- Landing page deploy/teardown.
- Campaign launch/reschedule/archive/manual event sync.
- Initial Access target import/bulk delete or enrichment jobs.
- SSH command/service actions.

## Workflow

1. Identify mutation endpoints and service functions in scope.
2. Check whether an audit event already exists and whether it has enough context.
3. Add logging close to the API boundary after successful mutation, unless the service is the only reliable place to know the outcome.
4. Include:
   - action name like `domain.checkout`, `project.member.add`, `provider.resource.delete`
   - entity type
   - entity ID
   - human-readable entity name
   - non-secret details as JSON-compatible dict
5. Do not include secrets, private keys, passwords, raw tokens, SMTP passwords, encrypted blobs, or full provider credentials.
6. On external provider mutations, log local intent/outcome and provider ID/label when non-secret.
7. Keep action names stable and searchable.

## Good Detail Fields

- `project_id`, `project_code`
- `provider`, `label`
- `resource_type`, `external_id`
- `domain`, `zone_id`, `record_type`
- `old_role`, `new_role`
- `status`, `operation`

## Bad Detail Fields

- API keys, tokens, passwords.
- Raw request payloads that may contain secrets.
- Private keys or SSH material.
- Full email content when it may contain sensitive target data, unless explicitly required and safe.

## Output

For reviews, lead with missing or weak audit events.

For implementations, report files changed, action names added, and any sensitive operations intentionally left unaudited with reason.
