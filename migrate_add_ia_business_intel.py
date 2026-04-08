#!/usr/bin/env python3
"""
One-time migration: create the ia_business_intel table.

Run inside the container:
    docker compose exec web python migrate_add_ia_business_intel.py

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
                "WHERE table_name='ia_business_intel'"
            ))
            if result.fetchone():
                print("+ Table 'ia_business_intel' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Creating 'ia_business_intel' table...")
            conn.execute(text("""
                CREATE TABLE ia_business_intel (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    company_overview TEXT,
                    key_products TEXT,
                    recent_news TEXT,
                    tech_stack TEXT,
                    key_departments TEXT,
                    vendor_partners TEXT,
                    social_presence TEXT,
                    raw_osint TEXT,
                    notes TEXT,
                    updated_by_id INTEGER REFERENCES users(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_ia_business_intel_project UNIQUE (project_id)
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_ia_business_intel_project_id ON ia_business_intel(project_id)"
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
