#!/usr/bin/env python3
"""
One-time migration: drop legacy scan_job_id column from ia_email_template_batches.

Batches now aggregate from all recon sources (tracked via data_sources column),
so the single-scan FK is obsolete.

Run inside the container:
    docker compose exec web python migrate_drop_batch_scan_job_id.py

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
                "WHERE table_name='ia_email_template_batches' "
                "AND column_name='scan_job_id'"
            ))
            if not result.fetchone():
                print("+ Column 'scan_job_id' already dropped -- migration already applied.")
                trans.rollback()
                return

            # Drop FK constraint first (Postgres names it <table>_<col>_fkey by default)
            print("Dropping FK constraint on 'scan_job_id'...")
            conn.execute(text(
                "ALTER TABLE ia_email_template_batches "
                "DROP CONSTRAINT IF EXISTS ia_email_template_batches_scan_job_id_fkey"
            ))

            print("Dropping 'scan_job_id' column from 'ia_email_template_batches'...")
            conn.execute(text(
                "ALTER TABLE ia_email_template_batches DROP COLUMN scan_job_id"
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
