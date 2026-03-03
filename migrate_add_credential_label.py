#!/usr/bin/env python3
"""
One-time migration: add `label` column to credentials (enables multiple accounts
per provider), update unique constraint, and add `credential_label` to domains.

Run inside the container:
    docker compose exec web python migrate_add_credential_label.py

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
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='credentials' AND column_name='label'"
            ))
            if result.fetchone():
                print("✓ Column 'label' already exists on credentials — migration already applied.")
                trans.rollback()
                return

            # --- credentials: add label column ---
            print("Adding 'label' to credentials...")
            conn.execute(text(
                "ALTER TABLE credentials "
                "ADD COLUMN label VARCHAR(100) NOT NULL DEFAULT 'default'"
            ))

            # --- credentials: replace unique constraint ---
            print("Replacing unique constraint on credentials...")
            conn.execute(text(
                "ALTER TABLE credentials DROP CONSTRAINT IF EXISTS uq_provider_key"
            ))
            conn.execute(text(
                "ALTER TABLE credentials "
                "ADD CONSTRAINT uq_provider_label_key "
                "UNIQUE (provider, label, key_name)"
            ))

            # --- domains: add credential_label column ---
            result2 = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='domains' AND column_name='credential_label'"
            ))
            if not result2.fetchone():
                print("Adding 'credential_label' to domains...")
                conn.execute(text(
                    "ALTER TABLE domains "
                    "ADD COLUMN credential_label VARCHAR(100) NOT NULL DEFAULT 'default'"
                ))
            else:
                print("✓ 'credential_label' already exists on domains.")

            trans.commit()
            print("✓ Migration complete.")

            result = conn.execute(text("SELECT COUNT(*) FROM credentials"))
            print(f"  credentials: {result.scalar()} rows (all existing rows now have label='default')")
            result = conn.execute(text("SELECT COUNT(*) FROM domains"))
            print(f"  domains: {result.scalar()} rows (all existing rows now have credential_label='default')")

        except Exception as e:
            trans.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
