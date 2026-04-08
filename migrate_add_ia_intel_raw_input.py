#!/usr/bin/env python3
"""
One-time migration: add raw_input column to ia_business_intel table.

Run inside the container:
    docker compose exec web python migrate_add_ia_intel_raw_input.py

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
                "WHERE table_name='ia_business_intel' AND column_name='raw_input'"
            ))
            if result.fetchone():
                print("+ Column 'raw_input' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Adding 'raw_input' column to 'ia_business_intel'...")
            conn.execute(text("ALTER TABLE ia_business_intel ADD COLUMN raw_input TEXT"))

            trans.commit()
            print("+ Migration complete.")

        except Exception as e:
            trans.rollback()
            print(f"x Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
