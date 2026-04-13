#!/usr/bin/env python3
"""
One-time migration: add data_sources column to ia_email_template_batches.

Run inside the container:
    docker compose exec web python migrate_add_batch_data_sources.py

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
                "WHERE table_name='ia_email_template_batches' "
                "AND column_name='data_sources'"
            ))
            if result.fetchone():
                print("+ Column 'data_sources' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Adding 'data_sources' TEXT column to 'ia_email_template_batches'...")
            conn.execute(text(
                "ALTER TABLE ia_email_template_batches ADD COLUMN data_sources TEXT"
            ))

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
