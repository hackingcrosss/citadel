---
name: ia-feature-builder
description: Build or extend InfraRed Initial Access features using the existing project-scoped IA model/service/API/template/Celery patterns. Use when adding IA targets, recon/discovery, FOFA/scanner, business intel, landing page, email template, campaign, or event functionality.
argument-hint: "<initial access feature>"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(rg *), Bash(git *), Bash(python *)
---

# Initial Access Feature Builder

Use this for changes under the Initial Access workspace.

## Existing IA Map

Pages:

- `/initial-access/`
- `/initial-access/scope`
- `/initial-access/recon`
- `/initial-access/targets`
- `/initial-access/campaigns`
- `/initial-access/landing-pages`
- `/initial-access/intel`
- `/initial-access/email-templates`
- `/initial-access/fofa`
- `/initial-access/discoveries`

API modules:

- `app/api/initial_access/__init__.py`
- `app/api/initial_access/targets.py`
- `app/api/initial_access/campaigns.py`
- `app/api/initial_access/landing_pages.py`
- `app/api/initial_access/business_intel.py`
- `app/api/initial_access/email_templates.py`
- `app/api/initial_access/fofa.py`
- `app/api/initial_access/discoveries.py`

Services:

- `ia_scan_service.py`
- `ia_target_service.py`
- `ia_business_intel_service.py`
- `ia_landing_service.py`
- `ia_campaign_service.py`
- `email_template_service.py`
- `fofa_service.py`
- `discovery_service.py`

Tasks:

- `app/tasks/initial_access_tasks.py`

Models:

- `IAScanJob`, `IATarget`, `IABusinessIntel`, `IAFofaSearch`
- `IALandingPage`
- `IAEmailTemplateBatch`, `IAEmailTemplate`
- `IACampaign`, `IACampaignEvent`

## Workflow

1. Identify the closest IA feature and read its model, service, API, and template.
2. Keep IA data project-scoped with `project_id`.
3. Require an active project for project-specific endpoints.
4. Block write actions for `auditor` and `white_team`.
5. Keep business logic in `app/services/`; routes should validate, authorize, call service, and serialize.
6. For long-running work, use `app/tasks/initial_access_tasks.py` and a status endpoint.
7. Add or update migration scripts for new model fields/tables.
8. Update `app/models/__init__.py` and `init_db.py` imports when needed for fresh installs.
9. Add page route/template changes in `app/routes.py` and `app/templates/`.
10. Add audit logs for bulk imports, generation, launches, deploys, teardown, and destructive actions.

## Data Rules

- Do not expose sensitive target data across projects.
- Treat FOFA/scanner/provider data as untrusted when rendered.
- Email and landing page HTML can be intentionally rich content; keep previews contained and avoid injecting it into app chrome unsafely.
- Campaign event raw data should be stored as JSON text and serialized carefully.
- Generated content should preserve enough metadata for traceability: project, source data, creator, timestamp, and provider IDs when pushed.

## Common IA Patterns

- `_require_active_project()` helper in API modules.
- `to_dict()` methods on models for API output.
- JSON text columns for flexible scope/results/raw data.
- Celery tasks update model status and error fields.
- Frontend fetch calls expect JSON and usually render Bootstrap tables/modals.

## Verification

- Run `python -m compileall app` if feasible.
- Check wrong-project access.
- Check auditor/white team read-only behavior.
- For generated/rendered content, run a quick XSS review.
- For async work, verify task status and failed-state display.

## Output

Report files changed, model/API/service/template/task pieces added, project-scope behavior, migrations, and verification performed.
