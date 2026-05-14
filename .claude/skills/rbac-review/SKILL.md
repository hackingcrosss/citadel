---
name: rbac-review
description: Review Citadel code changes for role-based access control mistakes across admin, project_admin, operator, white_team, and auditor users. Use for route/API/template reviews, authorization bugs, or when changes touch user roles, permissions, project membership, company access, or read-only behavior.
argument-hint: "[base-branch or files]"
context: fork
allowed-tools: Read, Grep, Glob, Bash(git *)
---

# RBAC Review

Review changed or requested files for Citadel authorization regressions.

## Role Model

Current roles:

- `admin`: global full access.
- `project_admin`: manages projects/companies, not global admin.
- `operator`: operational write access, usually scoped to project membership.
- `white_team`: company/project read-oriented user; may update allowed company profile fields.
- `auditor`: global read-only access.

Relevant helpers:

- `admin_required`
- `feature_required(feature_name)`
- `project_member_required(write=False)`
- `current_user.is_admin`, `.is_project_admin`, `.is_operator`, `.is_white_team`, `.is_auditor`
- `current_user.can_write_infra`, `.can_manage_projects`

## Workflow

1. Identify changed files or target files. If no files were supplied, inspect `git diff origin/develop --name-only`.
2. For routes and API endpoints, confirm every endpoint has `@login_required` unless intentionally public.
3. Confirm admin-only actions use `@admin_required` or equivalent explicit checks.
4. Confirm project-scoped actions validate membership through `project_member_required`, `project_service.can_read/can_write`, or equivalent active-project/resource checks.
5. Confirm mutation endpoints block `white_team` and `auditor`.
6. Confirm `project_admin` is only granted project/company management, not global infrastructure or admin-only power.
7. Confirm frontend hiding/disabling of controls is backed by backend checks.
8. Check serializers and list endpoints for cross-project or cross-company leakage.

## Common Citadel Failure Modes

- Treating `project_admin` as `admin`.
- Checking only `current_user.is_authenticated` on write endpoints.
- Filtering UI tables by active project but leaving API results unfiltered.
- Hiding a button for `IS_READONLY` while leaving the API writable.
- Letting white team update company structural fields such as `name`, `code`, `status`, or `industry`.
- Letting auditors use POST/PATCH/PUT/DELETE endpoints.
- Direct lookup by object ID without validating the object belongs to the active project/company.

## Output

Lead with findings, ordered by severity:

```text
[HIGH] app/api/example/__init__.py:42
Issue: Operator can update resources outside their active project.
Evidence: Endpoint loads by external_id without project_service check.
Fix: Gate with project_member_required(write=True) or assert_resource_writable().
```

If no issues are found, state that clearly and mention any residual test gaps.
