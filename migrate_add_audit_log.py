"""Migration: create audit_logs table.

Run once on existing deployments:
    docker compose exec web python migrate_add_audit_log.py
"""
from app import create_app, db

app = create_app()

with app.app_context():
    db.engine.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id          SERIAL PRIMARY KEY,
            timestamp   TIMESTAMP NOT NULL DEFAULT NOW(),
            user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
            user_email  VARCHAR(120) NOT NULL DEFAULT 'system',
            user_role   VARCHAR(20),
            action      VARCHAR(80) NOT NULL,
            entity_type VARCHAR(40),
            entity_id   VARCHAR(80),
            entity_name VARCHAR(255),
            details     TEXT,
            ip_address  VARCHAR(45)
        );
        CREATE INDEX IF NOT EXISTS ix_audit_logs_timestamp   ON audit_logs (timestamp DESC);
        CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id     ON audit_logs (user_id);
        CREATE INDEX IF NOT EXISTS ix_audit_logs_action      ON audit_logs (action);
        CREATE INDEX IF NOT EXISTS ix_audit_logs_entity_type ON audit_logs (entity_type);
    """)
    print("audit_logs table created (or already exists).")
