import json
from datetime import datetime
from app import db


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id          = db.Column(db.Integer, primary_key=True)
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    user_email  = db.Column(db.String(120), nullable=False, default='system')
    user_role   = db.Column(db.String(20))
    action      = db.Column(db.String(80),  nullable=False, index=True)   # e.g. 'domain.checkout'
    entity_type = db.Column(db.String(40),  index=True)                   # e.g. 'domain'
    entity_id   = db.Column(db.String(80))                                # str, works for int & uuid
    entity_name = db.Column(db.String(255))                               # human-readable label
    details     = db.Column(db.Text)                                      # JSON extra context
    ip_address  = db.Column(db.String(45))                                # IPv4 or IPv6

    user = db.relationship('User', foreign_keys=[user_id], lazy='joined')

    def to_dict(self):
        return {
            'id':          self.id,
            'timestamp':   self.timestamp.isoformat() + 'Z',
            'user_id':     self.user_id,
            'user_email':  self.user_email,
            'user_role':   self.user_role,
            'action':      self.action,
            'entity_type': self.entity_type,
            'entity_id':   self.entity_id,
            'entity_name': self.entity_name,
            'details':     json.loads(self.details) if self.details else None,
            'ip_address':  self.ip_address,
        }
