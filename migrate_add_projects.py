#!/usr/bin/env python3
"""
One-time migration: add project-based RBAC tables and domain checkout columns.

Creates:
  - projects          table
  - project_members   table
  - project_resources table

Modifies:
  - domains: adds checkout_project_id, checked_out_at, checked_out_by_id columns

Run inside the container:
    docker compose exec web python migrate_add_projects.py

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
                "WHERE table_schema='public' AND table_name='projects'"
            ))
            if result.fetchone():
                print("✓ Table 'projects' already exists — migration already applied.")
                trans.rollback()
                return

            # --- Create projects table ---
            print("Creating 'projects' table...")
            conn.execute(text("""
                CREATE TABLE projects (
                    id           SERIAL PRIMARY KEY,
                    name         VARCHAR(200) NOT NULL,
                    code         VARCHAR(30) NOT NULL,
                    description  TEXT,
                    status       VARCHAR(20) NOT NULL DEFAULT 'active',
                    created_by_id INTEGER REFERENCES users(id),
                    created_at   TIMESTAMP DEFAULT now(),
                    updated_at   TIMESTAMP DEFAULT now(),
                    CONSTRAINT uq_project_code UNIQUE (code)
                )
            """))
            conn.execute(text("CREATE INDEX ix_projects_code ON projects (code)"))

            # --- Create project_members table ---
            print("Creating 'project_members' table...")
            conn.execute(text("""
                CREATE TABLE project_members (
                    id           SERIAL PRIMARY KEY,
                    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_role VARCHAR(20) NOT NULL DEFAULT 'operator',
                    added_by_id  INTEGER REFERENCES users(id),
                    added_at     TIMESTAMP DEFAULT now(),
                    CONSTRAINT uq_project_member UNIQUE (project_id, user_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_project_members_project_id ON project_members (project_id)"))
            conn.execute(text("CREATE INDEX ix_project_members_user_id ON project_members (user_id)"))

            # --- Create project_resources table ---
            print("Creating 'project_resources' table...")
            conn.execute(text("""
                CREATE TABLE project_resources (
                    id            SERIAL PRIMARY KEY,
                    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    resource_type VARCHAR(30) NOT NULL,
                    external_id   VARCHAR(255) NOT NULL,
                    label         VARCHAR(255),
                    tagged_by_id  INTEGER REFERENCES users(id),
                    tagged_at     TIMESTAMP DEFAULT now(),
                    CONSTRAINT uq_project_resource UNIQUE (project_id, resource_type, external_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_project_resources_project_id ON project_resources (project_id)"))
            conn.execute(text("CREATE INDEX ix_project_resources_resource_type ON project_resources (resource_type)"))
            conn.execute(text("CREATE INDEX ix_project_resources_external_id ON project_resources (external_id)"))

            # --- Modify domains table: add checkout columns ---
            print("Adding checkout columns to 'domains' table...")
            conn.execute(text(
                "ALTER TABLE domains "
                "ADD COLUMN checkout_project_id INTEGER REFERENCES projects(id)"
            ))
            conn.execute(text(
                "ALTER TABLE domains "
                "ADD COLUMN checked_out_at TIMESTAMP"
            ))
            conn.execute(text(
                "ALTER TABLE domains "
                "ADD COLUMN checked_out_by_id INTEGER REFERENCES users(id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_domains_checkout_project_id ON domains (checkout_project_id)"
            ))

            # --- Create default project owned by the first admin ---
            print("Creating default project...")
            result = conn.execute(text(
                "SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1"
            ))
            admin_row = result.fetchone()
            if admin_row:
                admin_id = admin_row[0]
                result = conn.execute(text(
                    "INSERT INTO projects (name, code, description, status, created_by_id) "
                    "VALUES ('Default', 'DEFAULT', 'Default project for unassigned resources.', 'active', :admin_id) "
                    "RETURNING id"
                ), {'admin_id': admin_id})
                project_id = result.fetchone()[0]
                conn.execute(text(
                    "INSERT INTO project_members (project_id, user_id, project_role, added_by_id) "
                    "VALUES (:project_id, :admin_id, 'operator', :admin_id)"
                ), {'project_id': project_id, 'admin_id': admin_id})
                print(f"  Created default project (id={project_id}) owned by admin id={admin_id}")
            else:
                print("  No admin user found — skipping default project creation. Run init_db.py first.")

            trans.commit()
            print("✓ Migration complete.")

            result = conn.execute(text("SELECT COUNT(*) FROM projects"))
            print(f"  projects: {result.scalar()} row(s)")
            result = conn.execute(text("SELECT COUNT(*) FROM project_members"))
            print(f"  project_members: {result.scalar()} row(s)")
            result = conn.execute(text("SELECT COUNT(*) FROM domains"))
            print(f"  domains: {result.scalar()} rows (checkout columns added, all NULL = available in pool)")

        except Exception as e:
            trans.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
