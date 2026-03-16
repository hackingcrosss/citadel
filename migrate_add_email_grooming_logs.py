#!/usr/bin/env python3
"""
One-time migration: create `email_grooming_logs` table for tracking
individual warm-up emails sent via GoPhish.

Run inside the container:
    docker compose exec web python migrate_add_email_grooming_logs.py

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
                "WHERE table_name='email_grooming_logs'"
            ))
            if result.fetchone():
                print("Table 'email_grooming_logs' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Creating 'email_grooming_logs' table...")
            conn.execute(text("""
                CREATE TABLE email_grooming_logs (
                    id SERIAL PRIMARY KEY,
                    config_id INTEGER NOT NULL REFERENCES email_grooming_configs(id) ON DELETE CASCADE,
                    sent_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    from_address VARCHAR(255) NOT NULL,
                    to_address VARCHAR(255) NOT NULL,
                    subject VARCHAR(500) NOT NULL,
                    success BOOLEAN NOT NULL DEFAULT TRUE,
                    error_message TEXT,
                    gophish_profile_id INTEGER
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_email_grooming_logs_config_id ON email_grooming_logs(config_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_email_grooming_logs_sent_at ON email_grooming_logs(sent_at)"
            ))

            trans.commit()
            print("Migration complete -- email_grooming_logs table created.")

        except Exception as e:
            trans.rollback()
            print(f"Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
