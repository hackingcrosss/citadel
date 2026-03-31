---
name: infrared-deploy
description: Deploy InfraRed — rebuild containers, run migrations, verify health, tail logs.
disable-model-invocation: true
allowed-tools: Bash(docker compose *), Bash(git *)
---

# InfraRed Deploy

## Pre-flight
1. Check git status is clean (warn if uncommitted changes, but don't block):
   `git status --short`
2. Show current branch and last commit:
   `git log --oneline -1`
3. Validate compose file:
   `docker compose config --quiet`

## Build & Deploy
4. Rebuild and restart all services:
   `docker compose up -d --build`
5. Wait 10 seconds for services to stabilize.
6. Check all containers are running:
   `docker compose ps`

## Post-Deploy Verification
7. Check web container health — tail recent logs and look for errors:
   `docker compose logs web --tail=30 2>&1 | tail -30`
8. Check celery worker is connected:
   `docker compose logs celery --tail=15 2>&1 | tail -15`
9. Check database connectivity:
   `docker compose exec web python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.session.execute(db.text('SELECT 1')); print('DB: OK')"`

## Report
Summarize:
- Container status (all running? any restarting?)
- Any errors in web/celery logs
- Database connectivity
- Deploy result: SUCCESS or FAILED (with reason)
