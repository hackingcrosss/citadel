"""
Migration: Add users.company_id FK and rename viewer → auditor role.

Idempotent — safe to run multiple times.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    with db.engine.connect() as conn:
        # 1. Add company_id column to users (if not present)
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='company_id'"
        ))
        if not result.fetchone():
            print("Adding users.company_id column...")
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN company_id INTEGER REFERENCES companies(id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_users_company_id ON users (company_id)"
            ))
            conn.commit()
            print("  Done.")
        else:
            print("users.company_id already exists — skipping.")

        # 2. Rename viewer → auditor
        result = conn.execute(text(
            "SELECT COUNT(*) FROM users WHERE role = 'viewer'"
        ))
        viewer_count = result.scalar()
        if viewer_count:
            print(f"Renaming {viewer_count} viewer user(s) to auditor...")
            conn.execute(text("UPDATE users SET role='auditor' WHERE role='viewer'"))
            conn.commit()
            print("  Done.")
        else:
            print("No viewer users to rename — skipping.")

    print("\nMigration complete.")
