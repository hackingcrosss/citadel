#!/usr/bin/env python3
"""
One-time migration: create the ia_landing_pages table.

Run inside the container:
    docker compose exec web python migrate_add_ia_landing_pages.py

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
                "WHERE table_name='ia_landing_pages'"
            ))
            if result.fetchone():
                print("+ Table 'ia_landing_pages' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Creating 'ia_landing_pages' table...")
            conn.execute(text("""
                CREATE TABLE ia_landing_pages (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    name VARCHAR(200) NOT NULL,
                    page_type VARCHAR(30) DEFAULT 'cred_harvest',
                    status VARCHAR(30) DEFAULT 'draft',
                    domain_id INTEGER REFERENCES domains(id),
                    container_name VARCHAR(200),
                    npm_host_id INTEGER,
                    fqdn VARCHAR(300),
                    template_source VARCHAR(30) DEFAULT 'manual',
                    clone_url VARCHAR(500),
                    html_content TEXT,
                    gophish_page_id INTEGER,
                    capture_credentials BOOLEAN DEFAULT TRUE,
                    capture_passwords BOOLEAN DEFAULT FALSE,
                    redirect_url VARCHAR(500),
                    deployed_by_id INTEGER REFERENCES users(id),
                    deployed_at TIMESTAMP,
                    torn_down_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_ia_landing_pages_project_id ON ia_landing_pages(project_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_ia_landing_pages_status ON ia_landing_pages(status)"
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
