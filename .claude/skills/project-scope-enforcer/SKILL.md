---
name: project-scope-enforcer
description: Implement or repair InfraRed active-project scoping for APIs, services, templates, and resource mutations. Use when adding project-scoped features, fixing cross-project leakage, tagging resources to projects, or enforcing operator/white_team/auditor access.
argument-hint: "<feature or files>"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(rg *), Bash(git *)
---

# Project Scope Enforcer

Use this when a feature must respect InfraRed project membership and active-project boundaries.

## Core Concepts

- Active project is provided by `project_service.get_active_project(current_user)` and injected into templates as `active_project`.
- Resource ownership is tracked in `project_resources` using `resource_type` and `external_id`.
- Domains can be checked out to projects through `domains.checkout_project_id`.
- Admins bypass project checks.
- Auditors can read all projects but cannot write.
- White team users are read-only for infrastructure mutations.

## Preferred Helpers

Read `app/services/project_service.py` before editing. Prefer existing helpers:

- `get_active_project(user)`
- `get_projects_for_user(user)`
- `can_read(user, project_id)`
- `can_write(user, project_id)`
- `assert_domain_accessible(domain, user)`
- `tag_resource(project_id, resource_type, external_id, label, user_id)`
- `get_resource_project(resource_type, external_id)`
- `build_project_tag_map(resource_type, external_ids)`
- `filter_by_active_project(user, items, active_project)`
- `assert_resource_writable(resource_type, external_id, user)`

## Implementation Workflow

1. Identify whether the feature operates on a `Project`, `Domain`, or external resource.
2. Read the relevant API module and service module.
3. For read endpoints:
   - Admin/auditor may see broader data when intended.
   - Operators and white team should generally see only active-project resources.
   - Return clear empty results when no active project is selected, unless the page is allowed to be global.
4. For write endpoints:
   - Require `@login_required`.
   - Block `auditor` and `white_team`.
   - Validate active project or project membership before mutation.
   - Use `assert_resource_writable()` for external resources already tagged to another project.
5. For newly created external resources:
   - Tag them to the active project via `tag_resource(...)` when appropriate.
   - Include a human-readable `label`.
6. For templates:
   - Inject/use `ACTIVE_PROJECT_ID`, `ACTIVE_PROJECT_CODE`, `IS_AUDITOR`, `IS_WHITE_TEAM`, and `IS_READONLY` consistently.
   - Keep frontend gating as UX only; backend remains authoritative.
7. Add audit logging for meaningful scope changes or infrastructure mutations.

## Checks Before Finishing

- No operator can read or mutate another project by changing an ID in the URL/body.
- No unassigned external resource is accidentally claimed without explicit action.
- Admin behavior remains global where existing product behavior expects it.
- Auditor and white team writes return 403 JSON for API routes.
- Template controls match backend authorization.

## Output

Report changed files, scoping rule implemented, and any remaining ambiguous ownership cases.
