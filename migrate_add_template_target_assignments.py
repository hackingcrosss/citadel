#!/usr/bin/env python3
"""
One-time migration: create ia_template_target_assignments join table,
add gophish_group_id column to ia_email_templates,
and add email_template_id column to ia_campaigns.

Run inside the container:
    docker compose exec web python migrate_add_template_target_assignments.py

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
            # 1. Join table
            result = conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name='ia_template_target_assignments'"
            ))
            if result.fetchone():
                print("+ Table 'ia_template_target_assignments' already exists.")
            else:
                print("Creating 'ia_template_target_assignments' table...")
                conn.execute(text("""
                    CREATE TABLE ia_template_target_assignments (
                        template_id INTEGER NOT NULL REFERENCES ia_email_templates(id) ON DELETE CASCADE,
                        target_id INTEGER NOT NULL REFERENCES ia_targets(id) ON DELETE CASCADE,
                        assigned_at TIMESTAMP DEFAULT NOW(),
                        suggested BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (template_id, target_id)
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX ix_ia_tta_target_id ON ia_template_target_assignments(target_id)"
                ))
                print("+ Table created.")

            # 2. GoPhish group ID column on email templates
            result2 = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='ia_email_templates' AND column_name='gophish_group_id'"
            ))
            if result2.fetchone():
                print("+ Column 'gophish_group_id' already exists.")
            else:
                print("Adding 'gophish_group_id' column to ia_email_templates...")
                conn.execute(text(
                    "ALTER TABLE ia_email_templates ADD COLUMN gophish_group_id INTEGER"
                ))
                print("+ Column added.")

            # 3. Email template FK on campaigns
            result3 = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='ia_campaigns' AND column_name='email_template_id'"
            ))
            if result3.fetchone():
                print("+ Column 'email_template_id' on ia_campaigns already exists.")
            else:
                print("Adding 'email_template_id' column to ia_campaigns...")
                conn.execute(text(
                    "ALTER TABLE ia_campaigns ADD COLUMN email_template_id INTEGER "
                    "REFERENCES ia_email_templates(id)"
                ))
                print("+ Column added.")

            # 4. Phishing URL on campaigns
            result4 = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='ia_campaigns' AND column_name='phishing_url'"
            ))
            if result4.fetchone():
                print("+ Column 'phishing_url' on ia_campaigns already exists.")
            else:
                print("Adding 'phishing_url' column to ia_campaigns...")
                conn.execute(text(
                    "ALTER TABLE ia_campaigns ADD COLUMN phishing_url VARCHAR(500)"
                ))
                print("+ Column added.")

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
