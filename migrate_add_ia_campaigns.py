#!/usr/bin/env python3
"""
One-time migration: create ia_campaigns, ia_campaign_targets, and ia_campaign_events tables.

Run inside the container:
    docker compose exec web python migrate_add_ia_campaigns.py

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
            # Check if already applied
            result = conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name='ia_campaigns'"
            ))
            if result.fetchone():
                print("+ Table 'ia_campaigns' already exists -- migration already applied.")
                trans.rollback()
                return

            print("Creating 'ia_campaigns' table...")
            conn.execute(text("""
                CREATE TABLE ia_campaigns (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    name VARCHAR(200) NOT NULL,
                    vector VARCHAR(30) DEFAULT 'phishing',
                    status VARCHAR(30) DEFAULT 'draft',
                    domain_id INTEGER REFERENCES domains(id),
                    gophish_campaign_id INTEGER,
                    gophish_smtp_id INTEGER,
                    landing_page_id INTEGER,
                    scheduled_start TIMESTAMP,
                    scheduled_end TIMESTAMP,
                    roe_enforced BOOLEAN DEFAULT TRUE,
                    targets_count INTEGER DEFAULT 0,
                    emails_sent INTEGER DEFAULT 0,
                    opens_count INTEGER DEFAULT 0,
                    clicks_count INTEGER DEFAULT 0,
                    creds_captured INTEGER DEFAULT 0,
                    payloads_executed INTEGER DEFAULT 0,
                    created_by_id INTEGER REFERENCES users(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_ia_campaigns_project_id ON ia_campaigns(project_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_ia_campaigns_status ON ia_campaigns(status)"
            ))

            print("Creating 'ia_campaign_targets' table...")
            conn.execute(text("""
                CREATE TABLE ia_campaign_targets (
                    campaign_id INTEGER NOT NULL REFERENCES ia_campaigns(id) ON DELETE CASCADE,
                    target_id INTEGER NOT NULL REFERENCES ia_targets(id) ON DELETE CASCADE,
                    added_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (campaign_id, target_id)
                )
            """))

            print("Creating 'ia_campaign_events' table...")
            conn.execute(text("""
                CREATE TABLE ia_campaign_events (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER NOT NULL REFERENCES ia_campaigns(id) ON DELETE CASCADE,
                    target_id INTEGER REFERENCES ia_targets(id) ON DELETE SET NULL,
                    event_type VARCHAR(30) NOT NULL,
                    occurred_at TIMESTAMP DEFAULT NOW(),
                    source VARCHAR(30) DEFAULT 'gophish',
                    raw_data TEXT,
                    ip_address VARCHAR(45),
                    user_agent VARCHAR(500),
                    notes TEXT
                )
            """))
            conn.execute(text(
                "CREATE INDEX ix_ia_campaign_events_campaign_id ON ia_campaign_events(campaign_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_ia_campaign_events_target_id ON ia_campaign_events(target_id)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_ia_campaign_events_event_type ON ia_campaign_events(event_type)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_ia_campaign_events_occurred_at ON ia_campaign_events(occurred_at)"
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
