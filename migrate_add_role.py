#!/usr/bin/env python3
"""
One-time migration: replace the boolean `is_admin` column with a `role` VARCHAR.

Run inside the container:
    docker compose exec web python migrate_add_role.py

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
            # Check if `role` column already exists
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='role'"
            ))
            if result.fetchone():
                print("✓ Column 'role' already exists — migration already applied.")
                trans.rollback()
                return

            print("Adding 'role' column to users table...")
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'operator'"
            ))

            # Promote existing admin user(s) based on the old is_admin flag
            print("Migrating existing admin users...")
            conn.execute(text(
                "UPDATE users SET role = 'admin' WHERE is_admin = TRUE"
            ))

            # Drop the old is_admin column
            print("Dropping old 'is_admin' column...")
            conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS is_admin"))

            trans.commit()
            print("✓ Migration complete.")

            # Show results
            result = conn.execute(text("SELECT email, role FROM users ORDER BY id"))
            print("\nCurrent users:")
            for row in result:
                print(f"  {row[0]:40s}  role={row[1]}")

        except Exception as e:
            trans.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()

if __name__ == '__main__':
    run()
