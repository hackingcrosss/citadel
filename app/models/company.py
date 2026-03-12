from app import db
from datetime import datetime

COMPANY_STATUSES = ('active', 'archived')

# Fields that only admins may modify (structural identity of the company)
COMPANY_STRUCTURAL_FIELDS = frozenset({
    'name', 'code', 'description', 'status', 'industry',
})

# Fields that white team members may update (exercise-context info)
COMPANY_PROFILE_FIELDS = frozenset({
    'scope_notes', 'out_of_scope_notes', 'roe_notes', 'allowed_hours',
    'primary_contact_name', 'primary_contact_email', 'primary_contact_phone',
    'emergency_contact_name', 'emergency_contact_phone',
    'it_contact_name', 'it_contact_email',
    'notes',
})


class Company(db.Model):
    __tablename__ = 'companies'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    code = db.Column(db.String(30), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='active')  # active | archived
    industry = db.Column(db.String(100))

    # Exercise profile (white team writable)
    scope_notes = db.Column(db.Text)
    out_of_scope_notes = db.Column(db.Text)
    roe_notes = db.Column(db.Text)
    allowed_hours = db.Column(db.String(200))
    primary_contact_name = db.Column(db.String(200))
    primary_contact_email = db.Column(db.String(200))
    primary_contact_phone = db.Column(db.String(100))
    emergency_contact_name = db.Column(db.String(200))
    emergency_contact_phone = db.Column(db.String(100))
    it_contact_name = db.Column(db.String(200))
    it_contact_email = db.Column(db.String(200))
    notes = db.Column(db.Text)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    projects = db.relationship('Project', back_populates='company', lazy='dynamic')

    def to_dict(self, include_projects=False):
        d = {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'description': self.description,
            'status': self.status,
            'industry': self.industry,
            'scope_notes': self.scope_notes,
            'out_of_scope_notes': self.out_of_scope_notes,
            'roe_notes': self.roe_notes,
            'allowed_hours': self.allowed_hours,
            'primary_contact_name': self.primary_contact_name,
            'primary_contact_email': self.primary_contact_email,
            'primary_contact_phone': self.primary_contact_phone,
            'emergency_contact_name': self.emergency_contact_name,
            'emergency_contact_phone': self.emergency_contact_phone,
            'it_contact_name': self.it_contact_name,
            'it_contact_email': self.it_contact_email,
            'notes': self.notes,
            'project_count': self.projects.count(),
            'created_by_id': self.created_by_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_projects:
            d['projects'] = [p.to_dict() for p in self.projects.all()]
        return d

    def __repr__(self):
        return f'<Company {self.code}>'
