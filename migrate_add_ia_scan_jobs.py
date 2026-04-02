#!/usr/bin/env python3
"""
One-time migration: create the ia_scan_jobs table.

Run inside the container:
    docker compose exec web python migrate_add_ia_scan_jobs.py

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
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name='ia_scan_jobs'"
            ))
            if result.fetchone():
                print("+ Table 'ia_scan_jobs' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Creating 'ia_scan_jobs' table...")
            conn.execute(text("""
                CREATE TABLE ia_scan_jobs (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    external_job_id VARCHAR(255),
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    target_scope TEXT,
                    results_summary TEXT,
                    raw_results TEXT,
                    error_message TEXT,
                    triggered_by_id INTEGER REFERENCES users(id),
                    triggered_at TIMESTAMP DEFAULT NOW(),
                    completed_at TIMESTAMP,
                    polled_at TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_ia_scan_jobs_project_id ON ia_scan_jobs(project_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_ia_scan_jobs_external_job_id ON ia_scan_jobs(external_job_id)"
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
