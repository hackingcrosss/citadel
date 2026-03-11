#!/usr/bin/env python3
"""
One-time migration: create the cdn_distributions table.

Run inside the container:
    docker compose exec web python migrate_add_cdn.py

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
                "WHERE table_name='cdn_distributions'"
            ))
            if result.fetchone():
                print("✓ Table 'cdn_distributions' already exists — migration already applied.")
                trans.rollback()
                return

            print("Creating 'cdn_distributions' table...")
            conn.execute(text("""
                CREATE TABLE cdn_distributions (
                    id SERIAL PRIMARY KEY,
                    provider VARCHAR(50) NOT NULL,
                    account_label VARCHAR(100) NOT NULL DEFAULT 'default',
                    external_id VARCHAR(500),
                    domain VARCHAR(500),
                    origin_host VARCHAR(500),
                    origin_port INTEGER DEFAULT 443,
                    status VARCHAR(50) DEFAULT 'deploying',
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))

            trans.commit()
            print("✓ Migration complete.")

        except Exception as e:
            trans.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
