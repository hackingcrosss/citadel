#!/usr/bin/env python3
"""
One-time migration: create the ia_targets table.

Run inside the container:
    docker compose exec web python migrate_add_ia_targets.py

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
                "WHERE table_name='ia_targets'"
            ))
            if result.fetchone():
                print("+ Table 'ia_targets' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Creating 'ia_targets' table...")
            conn.execute(text("""
                CREATE TABLE ia_targets (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    first_name VARCHAR(100),
                    last_name VARCHAR(100),
                    email VARCHAR(255),
                    phone VARCHAR(50),
                    job_title VARCHAR(200),
                    department VARCHAR(200),
                    organisation VARCHAR(200),
                    linkedin_url VARCHAR(500),
                    notes TEXT,
                    breach_sources TEXT,
                    exposed_services TEXT,
                    osint_enriched_at TIMESTAMP,
                    source VARCHAR(50) DEFAULT 'manual',
                    created_by_id INTEGER REFERENCES users(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_ia_target_project_email UNIQUE (project_id, email)
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_ia_targets_project_id ON ia_targets(project_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_ia_targets_email ON ia_targets(email)"
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
