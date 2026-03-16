#!/usr/bin/env python3
"""
One-time migration: add `gophish_profile_id` column to `email_grooming_configs`.
NULL = rotate across all matching profiles for the domain.

Run inside the container:
    docker compose exec web python migrate_add_grooming_profile.py

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
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='email_grooming_configs' AND column_name='gophish_profile_id'"
            ))
            if result.fetchone():
                print("Column 'gophish_profile_id' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Adding 'gophish_profile_id' column to email_grooming_configs...")
            conn.execute(text(
                "ALTER TABLE email_grooming_configs ADD COLUMN gophish_profile_id INTEGER"
            ))

            trans.commit()
            print("Migration complete -- gophish_profile_id column added.")

        except Exception as e:
            trans.rollback()
            print(f"Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
