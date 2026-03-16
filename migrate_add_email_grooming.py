#!/usr/bin/env python3
"""
One-time migration: create `email_grooming_configs` table for email domain
reputation grooming (daily warm-up sends to target addresses).

Run inside the container:
    docker compose exec web python migrate_add_email_grooming.py

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
                "WHERE table_name='email_grooming_configs'"
            ))
            if result.fetchone():
                print("✓ Table 'email_grooming_configs' already exists — migration already applied.")
                trans.rollback()
                return

            print("Creating 'email_grooming_configs' table...")
            conn.execute(text("""
                CREATE TABLE email_grooming_configs (
                    id SERIAL PRIMARY KEY,
                    domain_id INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
                    target_email VARCHAR(255) NOT NULL,
                    emails_per_day INTEGER NOT NULL DEFAULT 10,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    emails_sent INTEGER NOT NULL DEFAULT 0,
                    last_sent_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_grooming_domain_target UNIQUE (domain_id, target_email)
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_email_grooming_configs_domain_id ON email_grooming_configs(domain_id)"
            ))

            trans.commit()
            print("✓ Migration complete — email_grooming_configs table created.")

        except Exception as e:
            trans.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
