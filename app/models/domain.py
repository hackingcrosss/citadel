from app import db
from datetime import datetime


class Domain(db.Model):
    __tablename__ = 'domains'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False, index=True)
    cloudflare_zone_id = db.Column(db.String(64), unique=True, index=True)
    registrar = db.Column(db.String(100))
    status = db.Column(db.String(30), default='active')  # active, inactive, pending
    purpose = db.Column(db.String(50))  # phishing, c2, redirect, staging
    notes = db.Column(db.Text)
    mailgun_region = db.Column(db.String(5))  # us, eu
    provider = db.Column(db.String(50), nullable=False, default='cloudflare')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = db.Column(db.DateTime)

    dns_records = db.relationship('DNSRecord', backref='domain', lazy='dynamic',
                                  cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'cloudflare_zone_id': self.cloudflare_zone_id,
            'registrar': self.registrar,
            'status': self.status,
            'purpose': self.purpose,
            'notes': self.notes,
            'mailgun_region': self.mailgun_region,
            'provider': self.provider,
            'record_count': self.dns_records.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None,
        }

    def __repr__(self):
        return f'<Domain {self.name}>'


class DNSRecord(db.Model):
    __tablename__ = 'dns_records'

    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domains.id'), nullable=False, index=True)
    cloudflare_record_id = db.Column(db.String(64), unique=True, index=True)
    record_type = db.Column(db.String(10), nullable=False)  # A, AAAA, CNAME, MX, TXT, etc.
    name = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    ttl = db.Column(db.Integer, default=1)  # 1 = auto
    proxied = db.Column(db.Boolean, default=False)
    priority = db.Column(db.Integer)  # for MX records
    managed_by = db.Column(db.String(30), default='manual')  # manual, infrared, mailgun
    provider = db.Column(db.String(50), nullable=False, default='cloudflare')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'domain_id': self.domain_id,
            'domain_name': self.domain.name if self.domain else None,
            'cloudflare_record_id': self.cloudflare_record_id,
            'record_type': self.record_type,
            'name': self.name,
            'content': self.content,
            'ttl': self.ttl,
            'proxied': self.proxied,
            'priority': self.priority,
            'managed_by': self.managed_by,
            'provider': self.provider,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<DNSRecord {self.record_type} {self.name}>'
