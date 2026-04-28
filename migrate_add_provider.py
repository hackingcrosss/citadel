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
            def column_exists(table_name, column_name):
                result = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:table_name "
                    "AND column_name=:column_name"
                ), {'table_name': table_name, 'column_name': column_name})
                return result.fetchone() is not None

            def constraint_exists(table_name, constraint_name):
                result = conn.execute(text(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE table_schema='public' AND table_name=:table_name "
                    "AND constraint_name=:constraint_name"
                ), {'table_name': table_name, 'constraint_name': constraint_name})
                return result.fetchone() is not None

            # --- domains ---
            if not column_exists('domains', 'provider'):
                print("Adding 'provider' to domains...")
                conn.execute(text(
                    "ALTER TABLE domains "
                    "ADD COLUMN provider VARCHAR(50) NOT NULL DEFAULT 'cloudflare'"
                ))
            else:
                print("✓ domains.provider already exists — skipping.")

            # --- dns_records ---
            if not column_exists('dns_records', 'provider'):
                print("Adding 'provider' to dns_records...")
                conn.execute(text(
                    "ALTER TABLE dns_records "
                    "ADD COLUMN provider VARCHAR(50) NOT NULL DEFAULT 'cloudflare'"
                ))
            else:
                print("✓ dns_records.provider already exists — skipping.")

            # --- instance_tags: add column + replace unique constraint ---
            if not column_exists('instance_tags', 'provider'):
                print("Adding 'provider' to instance_tags...")
                conn.execute(text(
                    "ALTER TABLE instance_tags "
                    "ADD COLUMN provider VARCHAR(50) NOT NULL DEFAULT 'aws'"
                ))
            else:
                print("✓ instance_tags.provider already exists — skipping.")

            conn.execute(text(
                "ALTER TABLE instance_tags DROP CONSTRAINT IF EXISTS uq_instance_tag"
            ))
            if not constraint_exists('instance_tags', 'uq_provider_instance_tag'):
                print("Adding provider-aware unique constraint to instance_tags...")
                conn.execute(text(
                    "ALTER TABLE instance_tags "
                    "ADD CONSTRAINT uq_provider_instance_tag "
                    "UNIQUE (provider, instance_id, tag)"
                ))
            else:
                print("✓ instance_tags provider-aware unique constraint already exists — skipping.")

            # --- instance_ssh_configs: add column + replace unique constraint ---
            if not column_exists('instance_ssh_configs', 'provider'):
                print("Adding 'provider' to instance_ssh_configs...")
                conn.execute(text(
                    "ALTER TABLE instance_ssh_configs "
                    "ADD COLUMN provider VARCHAR(50) NOT NULL DEFAULT 'aws'"
                ))
            else:
                print("✓ instance_ssh_configs.provider already exists — skipping.")

            # Drop the implicit unique index created by unique=True on instance_id
            conn.execute(text(
                "ALTER TABLE instance_ssh_configs "
                "DROP CONSTRAINT IF EXISTS instance_ssh_configs_instance_id_key"
            ))
            if not constraint_exists('instance_ssh_configs', 'uq_provider_instance_ssh'):
                print("Adding provider-aware unique constraint to instance_ssh_configs...")
                conn.execute(text(
                    "ALTER TABLE instance_ssh_configs "
                    "ADD CONSTRAINT uq_provider_instance_ssh "
                    "UNIQUE (provider, instance_id)"
                ))
            else:
                print("✓ instance_ssh_configs provider-aware unique constraint already exists — skipping.")

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
