#!/usr/bin/env python3
"""
One-time migration: add `plan_override` column to the users table.

Allows per-user plan overrides independent of the global license tier.
A NULL value means the user inherits the global license plan.

Run inside the container:
    docker compose exec web python migrate_add_plan_override.py

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
            # --- Idempotency guard ---
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='plan_override'"
            ))
            if result.fetchone():
                print("✓ Column 'plan_override' already exists on users — migration already applied.")
                trans.rollback()
                return

            print("Adding 'plan_override' to users...")
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN plan_override VARCHAR(20) DEFAULT NULL"
            ))

            trans.commit()
            print("✓ Migration complete.")

            result = conn.execute(text("SELECT COUNT(*) FROM users"))
            count = result.scalar()
            print(f"  users: {count} rows (all default to NULL — inherit global license)")

        except Exception as e:
            trans.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
