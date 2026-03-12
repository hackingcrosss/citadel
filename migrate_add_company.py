#!/usr/bin/env python3
"""
One-time migration: add companies table and link projects to companies.

Creates:
  - companies  table

Modifies:
  - projects: adds company_id column

Run inside the container:
    docker compose exec web python migrate_add_company.py

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
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='companies'"
            ))
            if result.fetchone():
                print("✓ Table 'companies' already exists — migration already applied.")
                trans.rollback()
                return

            # --- Create companies table ---
            print("Creating 'companies' table...")
            conn.execute(text("""
                CREATE TABLE companies (
                    id                      SERIAL PRIMARY KEY,
                    name                    VARCHAR(200) NOT NULL,
                    code                    VARCHAR(30)  NOT NULL,
                    description             TEXT,
                    status                  VARCHAR(20)  NOT NULL DEFAULT 'active',
                    industry                VARCHAR(100),
                    scope_notes             TEXT,
                    out_of_scope_notes      TEXT,
                    roe_notes               TEXT,
                    allowed_hours           VARCHAR(200),
                    primary_contact_name    VARCHAR(200),
                    primary_contact_email   VARCHAR(200),
                    primary_contact_phone   VARCHAR(100),
                    emergency_contact_name  VARCHAR(200),
                    emergency_contact_phone VARCHAR(100),
                    it_contact_name         VARCHAR(200),
                    it_contact_email        VARCHAR(200),
                    notes                   TEXT,
                    created_by_id           INTEGER REFERENCES users(id),
                    created_at              TIMESTAMP DEFAULT now(),
                    updated_at              TIMESTAMP DEFAULT now(),
                    CONSTRAINT uq_company_name UNIQUE (name),
                    CONSTRAINT uq_company_code UNIQUE (code)
                )
            """))
            conn.execute(text("CREATE INDEX ix_companies_code ON companies (code)"))

            # --- Add company_id to projects ---
            print("Adding company_id to 'projects' table...")
            conn.execute(text(
                "ALTER TABLE projects ADD COLUMN company_id INTEGER REFERENCES companies(id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_projects_company_id ON projects (company_id)"
            ))

            trans.commit()
            print("✓ Migration complete.")

            result = conn.execute(text("SELECT COUNT(*) FROM companies"))
            print(f"  companies: {result.scalar()} row(s)")
            result = conn.execute(text("SELECT COUNT(*) FROM projects"))
            print(f"  projects: {result.scalar()} row(s) (company_id added, all NULL = unassigned)")

        except Exception as e:
            trans.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
