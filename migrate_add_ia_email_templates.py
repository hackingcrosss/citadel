#!/usr/bin/env python3
"""
One-time migration: create ia_email_template_batches and ia_email_templates tables.

Run inside the container:
    docker compose exec web python migrate_add_ia_email_templates.py

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
            # Check if batch table already exists
            result = conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name='ia_email_template_batches'"
            ))
            if result.fetchone():
                print("+ Table 'ia_email_template_batches' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Creating 'ia_email_template_batches' table...")
            conn.execute(text("""
                CREATE TABLE ia_email_template_batches (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    scan_job_id INTEGER REFERENCES ia_scan_jobs(id),
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    generated_by_id INTEGER REFERENCES users(id),
                    generated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_ia_etb_project_id ON ia_email_template_batches(project_id)"
            ))

            print("Creating 'ia_email_templates' table...")
            conn.execute(text("""
                CREATE TABLE ia_email_templates (
                    id SERIAL PRIMARY KEY,
                    batch_id INTEGER NOT NULL REFERENCES ia_email_template_batches(id) ON DELETE CASCADE,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    name VARCHAR(200),
                    subject TEXT NOT NULL,
                    html_body TEXT,
                    text_body TEXT,
                    pretext_category VARCHAR(100),
                    target_roles TEXT,
                    sender_suggestion VARCHAR(300),
                    relevance_score INTEGER,
                    notes TEXT,
                    gophish_template_id INTEGER,
                    pushed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_ia_et_project_id ON ia_email_templates(project_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_ia_et_batch_id ON ia_email_templates(batch_id)"
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
