from app import db
from datetime import datetime


class IATarget(db.Model):
    __tablename__ = 'ia_targets'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    email = db.Column(db.String(255), index=True)
    phone = db.Column(db.String(50))
    job_title = db.Column(db.String(200))
    department = db.Column(db.String(200))
    organisation = db.Column(db.String(200))
    linkedin_url = db.Column(db.String(500))
    notes = db.Column(db.Text)

    # OSINT enrichment from recon scans
    breach_sources = db.Column(db.Text)       # JSON: [{source, year, password_hash}]
    exposed_services = db.Column(db.Text)     # JSON: [{service, host, port}]
    osint_enriched_at = db.Column(db.DateTime)

    source = db.Column(db.String(50), default='manual')  # manual | import | osint
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', foreign_keys=[project_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    __table_args__ = (
        db.UniqueConstraint('project_id', 'email', name='uq_ia_target_project_email'),
    )

    @property
    def full_name(self):
        parts = [self.first_name or '', self.last_name or '']
        return ' '.join(p for p in parts if p).strip() or None

    @property
    def is_enriched(self):
        return self.osint_enriched_at is not None

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'project_id': self.project_id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.full_name,
            'email': self.email,
            'phone': self.phone,
            'job_title': self.job_title,
            'department': self.department,
            'organisation': self.organisation,
            'linkedin_url': self.linkedin_url,
            'notes': self.notes,
            'breach_sources': json.loads(self.breach_sources) if self.breach_sources else [],
            'exposed_services': json.loads(self.exposed_services) if self.exposed_services else [],
            'osint_enriched_at': self.osint_enriched_at.isoformat() if self.osint_enriched_at else None,
            'is_enriched': self.is_enriched,
            'source': self.source,
            'created_by': self.created_by.display_name if self.created_by else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
