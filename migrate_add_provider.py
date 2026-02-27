#!/usr/bin/env python3
"""
One-time migration: add `provider` column to domains, dns_records,
instance_tags, and instance_ssh_configs tables.

Also updates unique constraints on instance_tags and instance_ssh_configs
to include provider, enabling per-provider uniqueness in future.

Run inside the container:
    docker compose exec web python migrate_add_provider.py

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
                "WHERE table_name='domains' AND column_name='provider'"
            ))
            if result.fetchone():
                print("✓ Column 'provider' already exists on domains — migration already applied.")
                trans.rollback()
                return

            # --- domains ---
            print("Adding 'provider' to domains...")
            conn.execute(text(
                "ALTER TABLE domains "
                "ADD COLUMN provider VARCHAR(50) NOT NULL DEFAULT 'cloudflare'"
            ))

            # --- dns_records ---
            print("Adding 'provider' to dns_records...")
            conn.execute(text(
                "ALTER TABLE dns_records "
                "ADD COLUMN provider VARCHAR(50) NOT NULL DEFAULT 'cloudflare'"
            ))

            # --- instance_tags: add column + replace unique constraint ---
            print("Adding 'provider' to instance_tags and updating unique constraint...")
            conn.execute(text(
                "ALTER TABLE instance_tags "
                "ADD COLUMN provider VARCHAR(50) NOT NULL DEFAULT 'aws'"
            ))
            conn.execute(text(
                "ALTER TABLE instance_tags DROP CONSTRAINT IF EXISTS uq_instance_tag"
            ))
            conn.execute(text(
                "ALTER TABLE instance_tags "
                "ADD CONSTRAINT uq_provider_instance_tag "
                "UNIQUE (provider, instance_id, tag)"
            ))

            # --- instance_ssh_configs: add column + replace unique constraint ---
            print("Adding 'provider' to instance_ssh_configs and updating unique constraint...")
            conn.execute(text(
                "ALTER TABLE instance_ssh_configs "
                "ADD COLUMN provider VARCHAR(50) NOT NULL DEFAULT 'aws'"
            ))
            # Drop the implicit unique index created by unique=True on instance_id
            conn.execute(text(
                "ALTER TABLE instance_ssh_configs "
                "DROP CONSTRAINT IF EXISTS instance_ssh_configs_instance_id_key"
            ))
            conn.execute(text(
                "ALTER TABLE instance_ssh_configs "
                "ADD CONSTRAINT uq_provider_instance_ssh "
                "UNIQUE (provider, instance_id)"
            ))

            trans.commit()
            print("✓ Migration complete.")

            # Show summary
            for table in ('domains', 'dns_records', 'instance_tags', 'instance_ssh_configs'):
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.scalar()
                print(f"  {table}: {count} rows updated to default provider")

        except Exception as e:
            trans.rollback()
            print(f"✗ Migration failed: {e}")
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
