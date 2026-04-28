from app import db
from datetime import datetime


class Phishlet(db.Model):
    __tablename__ = 'phishlets'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    phishlet_name = db.Column(db.String(120))
    domain_id = db.Column(db.Integer, db.ForeignKey('domains.id'), nullable=False)
    cloudflare_zone_id = db.Column(db.String(64), nullable=False)
    credential_label = db.Column(db.String(120), default='default')
    target_ip = db.Column(db.String(64), nullable=False)

    yaml_content = db.Column(db.Text, nullable=False)

    bot_protection_enabled = db.Column(db.Boolean, default=True)
    bot_rule_id = db.Column(db.String(64))

    # parsed | deploying | live | error | torn_down
    status = db.Column(db.String(30), default='parsed', index=True)
    last_error = db.Column(db.Text)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    deployed_at = db.Column(db.DateTime)
    torn_down_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', foreign_keys=[project_id])
    domain = db.relationship('Domain', foreign_keys=[domain_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    dns_records = db.relationship(
        'PhishletDNSRecord',
        backref='phishlet',
        cascade='all, delete-orphan',
        lazy='select',
    )

    def to_dict(self, include_yaml=False):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'name': self.name,
            'phishlet_name': self.phishlet_name,
            'domain_id': self.domain_id,
            'domain_name': self.domain.name if self.domain else None,
            'cloudflare_zone_id': self.cloudflare_zone_id,
            'credential_label': self.credential_label,
            'target_ip': self.target_ip,
            'bot_protection_enabled': self.bot_protection_enabled,
            'bot_rule_id': self.bot_rule_id,
            'status': self.status,
            'last_error': self.last_error,
            'records': [r.to_dict() for r in self.dns_records],
            'created_by': self.created_by.display_name if self.created_by else None,
            'deployed_at': self.deployed_at.isoformat() if self.deployed_at else None,
            'torn_down_at': self.torn_down_at.isoformat() if self.torn_down_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'yaml_content': self.yaml_content if include_yaml else None,
        }


class PhishletDNSRecord(db.Model):
    __tablename__ = 'phishlet_dns_records'

    id = db.Column(db.Integer, primary_key=True)
    phishlet_id = db.Column(
        db.Integer,
        db.ForeignKey('phishlets.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    phish_sub = db.Column(db.String(120))
    fqdn = db.Column(db.String(300), nullable=False)
    cloudflare_record_id = db.Column(db.String(64))
    # created | exists | error | removed
    status = db.Column(db.String(30), default='created')
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'phish_sub': self.phish_sub,
            'fqdn': self.fqdn,
            'cloudflare_record_id': self.cloudflare_record_id,
            'status': self.status,
            'error_message': self.error_message,
        }
