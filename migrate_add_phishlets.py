#!/usr/bin/env python3
"""
One-time migration: create the phishlets and phishlet_dns_records tables.

Run inside the container:
    docker compose exec web python migrate_add_phishlets.py

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
            existing = conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN ('phishlets', 'phishlet_dns_records')"
            )).fetchall()
            existing_names = {row[0] for row in existing}

            if 'phishlets' in existing_names and 'phishlet_dns_records' in existing_names:
                print("+ Tables already exist -- migration already applied.")
                trans.rollback()
                return

            if 'phishlets' not in existing_names:
                print("Creating 'phishlets' table...")
                conn.execute(text("""
                    CREATE TABLE phishlets (
                        id SERIAL PRIMARY KEY,
                        project_id INTEGER NOT NULL REFERENCES projects(id),
                        name VARCHAR(200) NOT NULL,
                        phishlet_name VARCHAR(120),
                        domain_id INTEGER NOT NULL REFERENCES domains(id),
                        cloudflare_zone_id VARCHAR(64) NOT NULL,
                        credential_label VARCHAR(120) DEFAULT 'default',
                        target_ip VARCHAR(64) NOT NULL,
                        yaml_content TEXT NOT NULL,
                        bot_protection_enabled BOOLEAN DEFAULT TRUE,
                        bot_rule_id VARCHAR(64),
                        status VARCHAR(30) DEFAULT 'parsed',
                        last_error TEXT,
                        created_by_id INTEGER REFERENCES users(id),
                        deployed_at TIMESTAMP,
                        torn_down_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_phishlets_project_id ON phishlets(project_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_phishlets_status ON phishlets(status)"
                ))

            if 'phishlet_dns_records' not in existing_names:
                print("Creating 'phishlet_dns_records' table...")
                conn.execute(text("""
                    CREATE TABLE phishlet_dns_records (
                        id SERIAL PRIMARY KEY,
                        phishlet_id INTEGER NOT NULL REFERENCES phishlets(id) ON DELETE CASCADE,
                        phish_sub VARCHAR(120),
                        fqdn VARCHAR(300) NOT NULL,
                        cloudflare_record_id VARCHAR(64),
                        status VARCHAR(30) DEFAULT 'created',
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_phishlet_dns_records_phishlet_id "
                    "ON phishlet_dns_records(phishlet_id)"
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
