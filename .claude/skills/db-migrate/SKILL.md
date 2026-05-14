---
name: db-migrate
description: Create a database migration script following Citadel's migration pattern, then apply it.
disable-model-invocation: true
argument-hint: "<description>"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(docker compose *), Bash(python3 *)
---

# Database Migration

Create and apply a migration for: **$ARGUMENTS**

## Step 1: Analyze

Read the relevant model file(s) in `app/models/` to understand the schema change needed.

## Step 2: Check Existing Migrations

List existing migration scripts to follow the naming convention:
```
migrate_add_*.py
```
Read the most recent one to match the pattern exactly.

## Step 3: Create Migration Script

Create `migrate_<description>.py` in the project root following this pattern:

```python
"""
Migration: <description>
Run: docker compose exec web python migrate_<name>.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app, db

app = create_app()

def migrate():
    with app.app_context():
        conn = db.session.connection()
        
        # Check if migration already applied
        result = conn.execute(db.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = '<table>' AND column_name = '<column>'"
        ))
        if result.fetchone():
            print('[migrate] Column <column> already exists — skipping')
            return
        
        # Apply migration
        conn.execute(db.text("ALTER TABLE <table> ADD COLUMN <column> <type>"))
        
        # Set defaults for existing rows if needed
        # conn.execute(db.text("UPDATE <table> SET <column> = '<default>'"))
        
        db.session.commit()
        print('[migrate] Done — added <column> to <table>')

if __name__ == '__main__':
    migrate()
```

## Step 4: Apply

Run the migration inside the web container:
```
docker compose exec web python migrate_<name>.py
```

## Step 5: Verify

Confirm the migration applied:
```
docker compose exec web python -c "
from app import create_app, db
app = create_app()
with app.app_context():
    result = db.session.execute(db.text(\"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '<table>' ORDER BY ordinal_position\"))
    for row in result: print(f'  {row[0]}: {row[1]}')
"
```

Report: migration script path, what changed, verification result.
