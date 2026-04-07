#!/usr/bin/env python3
"""
One-time migration: add scope column to projects table.

Adds:
  - projects.scope  TEXT (JSON: {"domains":[], "cidrs":[], "ips":[], "notes":""})

Run inside the container:
    docker compose exec web python migrate_add_project_scope.py

Safe to run multiple times (idempotent).
"""

from app import create_app, db
from sqlalchemy import text


def run():
    app = create_app()
    with app.app_context():
        conn = db.engine.connect()
        trans = conn.begin()

        try:
            # Check if column already exists
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'projects' AND column_name = 'scope'"
            ))
            if result.fetchone():
                print('[OK] projects.scope column already exists — nothing to do.')
                trans.rollback()
                return

            conn.execute(text('ALTER TABLE projects ADD COLUMN scope TEXT'))
            print('[+] Added projects.scope column')

            trans.commit()
            print('[OK] Migration complete.')

        except Exception as e:
            trans.rollback()
            print(f'[ERROR] Migration failed: {e}')
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
