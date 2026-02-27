from datetime import datetime
from app import db


class License(db.Model):
    """Single-row table that stores the active plan/license for this InfraRed instance.

    The admin selects a tier manually via /admin/license.
    License key validation is reserved for a future phase.
    """
    __tablename__ = 'license'

    id = db.Column(db.Integer, primary_key=True)
    tier = db.Column(db.String(20), nullable=False, default='community')
    org_name = db.Column(db.String(200), default='')
    # Reserved for future cryptographic validation — not used yet
    license_key = db.Column(db.Text, default='')
    # Optional per-instance overrides: if set, these override the tier defaults
    custom_max_users = db.Column(db.Integer)
    custom_max_domains = db.Column(db.Integer)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    def __repr__(self):
        return f'<License tier={self.tier} org={self.org_name!r}>'
