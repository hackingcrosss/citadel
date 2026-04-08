#!/usr/bin/env python3
"""
One-time migration: create ia_fofa_searches table.

Run inside the container:
    docker compose exec web python migrate_add_ia_fofa_searches.py

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
                "WHERE table_name='ia_fofa_searches'"
            ))
            if result.fetchone():
                print("+ Table 'ia_fofa_searches' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Creating 'ia_fofa_searches' table...")
            conn.execute(text("""
                CREATE TABLE ia_fofa_searches (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    query TEXT NOT NULL,
                    scope_type VARCHAR(20),
                    scope_value VARCHAR(500),
                    total_results INTEGER,
                    results_count INTEGER,
                    raw_results TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    searched_by_id INTEGER REFERENCES users(id),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_ia_fofa_project_id ON ia_fofa_searches(project_id)"
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
