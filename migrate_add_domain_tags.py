#!/usr/bin/env python3
"""
One-time migration: create `domain_grooming_tags` table for annotating pool
domains with grooming labels (phishing, c2-redirect, mailgun_ready, etc.).

Run inside the container:
    docker compose exec web python migrate_add_domain_tags.py

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
                "WHERE table_name='domain_grooming_tags'"
            ))
            if result.fetchone():
                print("✓ Table 'domain_grooming_tags' already exists — migration already applied.")
                trans.rollback()
                return

            print("Creating 'domain_grooming_tags' table...")
            conn.execute(text("""
                CREATE TABLE domain_grooming_tags (
                    id SERIAL PRIMARY KEY,
                    domain_id INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
                    tag VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_domain_grooming_tag UNIQUE (domain_id, tag)
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_domain_grooming_tags_domain_id ON domain_grooming_tags(domain_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_domain_grooming_tags_tag ON domain_grooming_tags(tag)"
            ))

            trans.commit()
            print("✓ Migration complete — domain_grooming_tags table created.")

        except Exception as e:
            trans.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
