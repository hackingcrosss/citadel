---
name: celery-task-builder
description: Build InfraRed Celery background jobs with Flask app context, task logging, status endpoints, polling UI, idempotent service boundaries, and safe error handling. Use when adding async scans, provider operations, generation jobs, email grooming, deployment tasks, or long-running workflows.
argument-hint: "<task description>"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(rg *), Bash(git *), Bash(python *)
---

# Celery Task Builder

Use this for new or repaired background workflows.

## Existing Places To Read First

- `app/tasks/celery_app.py`: Celery setup and Flask app context.
- `app/services/task_log_service.py`: task log storage.
- `app/tasks/website_generator_tasks.py`: website generation pattern.
- `app/tasks/initial_access_tasks.py`: IA scan/template/intel/FOFA tasks.
- `app/tasks/cdn_tasks.py`: provider provisioning task pattern.

## Workflow

1. Keep provider/API/business logic in a service module; Celery task should orchestrate.
2. Define the task in the relevant `app/tasks/*.py` module.
3. Use the existing Celery app from `app/tasks/celery_app.py`.
4. Pass primitive IDs and data into tasks. Do not pass model objects, `current_user`, request objects, sessions, or provider clients.
5. Re-load database objects inside task execution.
6. Record task status/progress using the existing task log/status pattern when the UI needs progress.
7. Add or reuse a status endpoint for frontend polling.
8. Make retries explicit and safe. Avoid retrying non-idempotent external mutations unless the service can detect existing resources.
9. On failure:
   - Store a clear non-secret error on the local job/model.
   - Log server-side detail without credentials.
   - Return/persist a user-safe status.
10. Update frontend polling code only after confirming response shape.

## Safety Rules

- Do not access `current_user`, `request`, or `session` in tasks.
- Do not leak API keys, SMTP passwords, private keys, or encrypted values into task metadata/logs.
- Do not keep SDK clients in global state unless the existing provider service already does that safely.
- For external provisioning, store enough IDs for cleanup or resume.
- For generated content, persist intermediate status so page refreshes can recover.

## API Status Pattern

Status responses should be easy for templates to poll:

```json
{
  "status": "pending|running|completed|failed",
  "progress": 0,
  "message": "",
  "result": {}
}
```

Match nearby endpoint conventions if they differ.

## Verification

- Run `python -m compileall app` if feasible.
- Confirm the task imports cleanly.
- If containers are running, start a task and poll its status endpoint.
- Check failure behavior with missing credentials or invalid inputs.

## Output

Report task name, trigger endpoint, status endpoint, persisted state, retry/idempotency behavior, and verification performed.
