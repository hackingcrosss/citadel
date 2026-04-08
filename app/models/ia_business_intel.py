from app import db
from datetime import datetime


INTEL_FIELDS = frozenset({
    'company_overview', 'key_products', 'recent_news', 'tech_stack',
    'key_departments', 'vendor_partners', 'social_presence',
    'raw_osint', 'notes', 'raw_input',
})


class IABusinessIntel(db.Model):
    __tablename__ = 'ia_business_intel'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, unique=True, index=True)

    company_overview = db.Column(db.Text)
    key_products = db.Column(db.Text)
    recent_news = db.Column(db.Text)
    tech_stack = db.Column(db.Text)
    key_departments = db.Column(db.Text)
    vendor_partners = db.Column(db.Text)
    social_presence = db.Column(db.Text)
    raw_osint = db.Column(db.Text)
    notes = db.Column(db.Text)
    raw_input = db.Column(db.Text)

    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', foreign_keys=[project_id])
    updated_by = db.relationship('User', foreign_keys=[updated_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'company_overview': self.company_overview or '',
            'key_products': self.key_products or '',
            'recent_news': self.recent_news or '',
            'tech_stack': self.tech_stack or '',
            'key_departments': self.key_departments or '',
            'vendor_partners': self.vendor_partners or '',
            'social_presence': self.social_presence or '',
            'raw_osint': self.raw_osint or '',
            'notes': self.notes or '',
            'raw_input': self.raw_input or '',
            'updated_by': self.updated_by.display_name if self.updated_by else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
