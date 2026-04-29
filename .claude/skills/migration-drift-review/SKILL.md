---
name: migration-drift-review
description: Review InfraRed database schema drift between SQLAlchemy models, root-level migrate_add_*.py scripts, init_db.py imports, and runtime expectations. Use before release, after model changes, or when migrations/schema are suspected to be inconsistent.
argument-hint: "[model or migration]"
context: fork
allowed-tools: Read, Grep, Glob, Bash(rg *), Bash(git *)
---

# Migration Drift Review

Use this to find schema mismatch risk without necessarily creating a migration.

## Scope

Compare:

- `app/models/*.py`
- root `migrate_add_*.py` scripts
- `init_db.py`
- services/API code that reads or writes newly added fields
- any Flask-Migrate artifacts if present

## Workflow

1. Identify changed model files or target model names. If none supplied, inspect `git diff origin/develop --name-only`.
2. For each changed model:
   - Capture table name, new/removed columns, constraints, indexes, relationships, defaults, nullability.
   - Check whether a root-level migration script applies the same change idempotently.
   - Check whether `init_db.py` imports the model if `db.create_all()` should create it for fresh installs.
3. For each migration script:
   - Confirm it checks whether the change already exists before applying.
   - Confirm it uses `db.text(...)` for SQL strings.
   - Confirm it commits or rolls back cleanly.
   - Confirm defaults/backfills match model defaults and nullable constraints.
4. Check service/API/template code for assumptions about fields that may not exist on older databases.
5. If containers are running and the user asked for live verification, inspect `information_schema` from the `web` container.

## Common Drift Risks

- Model added but not imported in `app/models/__init__.py` or `init_db.py`.
- Migration adds a nullable column but model marks it non-nullable.
- Migration default differs from SQLAlchemy default.
- New unique constraint not represented in migration.
- Fresh installs get a table from `db.create_all()` but existing installs miss it.
- Existing installs get migration changes but fresh installs miss imports.
- Services reference new columns before migration has run.

## Output

Lead with findings:

```text
[MEDIUM] app/models/example.py:18
Issue: Model adds non-null column but no backfill/default migration was found.
Fix: Add idempotent migrate_add_example.py with ALTER TABLE, UPDATE backfill, then SET NOT NULL.
```

If no drift is found, state that and mention whether this was static-only or live DB verified.
