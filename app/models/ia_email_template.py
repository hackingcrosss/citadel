import json
from app import db
from datetime import datetime


BATCH_STATUSES = ('pending', 'completed', 'failed')

TEMPLATE_EDITABLE_FIELDS = frozenset({
    'name', 'subject', 'html_body', 'text_body', 'notes',
})


class IAEmailTemplateBatch(db.Model):
    __tablename__ = 'ia_email_template_batches'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    scan_job_id = db.Column(db.Integer, db.ForeignKey('ia_scan_jobs.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    error_message = db.Column(db.Text)
    generated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', foreign_keys=[project_id])
    scan_job = db.relationship('IAScanJob', foreign_keys=[scan_job_id])
    generated_by = db.relationship('User', foreign_keys=[generated_by_id])
    templates = db.relationship('IAEmailTemplate', back_populates='batch', cascade='all, delete-orphan',
                                order_by='IAEmailTemplate.relevance_score.desc()')

    def to_dict(self, include_templates=False):
        d = {
            'id': self.id,
            'project_id': self.project_id,
            'scan_job_id': self.scan_job_id,
            'status': self.status,
            'error_message': self.error_message,
            'generated_by': self.generated_by.display_name if self.generated_by else None,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'template_count': len(self.templates),
        }
        if include_templates:
            d['templates'] = [t.to_dict() for t in self.templates]
        return d


class IAEmailTemplate(db.Model):
    __tablename__ = 'ia_email_templates'

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('ia_email_template_batches.id', ondelete='CASCADE'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)

    name = db.Column(db.String(200))
    subject = db.Column(db.Text, nullable=False)
    html_body = db.Column(db.Text)
    text_body = db.Column(db.Text)
    pretext_category = db.Column(db.String(100))
    target_roles = db.Column(db.Text)          # JSON array: ["Finance", "IT Admin"]
    sender_suggestion = db.Column(db.String(300))
    relevance_score = db.Column(db.Integer)    # 1-10
    notes = db.Column(db.Text)

    gophish_template_id = db.Column(db.Integer, nullable=True)
    pushed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    batch = db.relationship('IAEmailTemplateBatch', back_populates='templates')

    @property
    def parsed_target_roles(self):
        if not self.target_roles:
            return []
        try:
            return json.loads(self.target_roles)
        except (json.JSONDecodeError, TypeError):
            return []

    def to_dict(self):
        return {
            'id': self.id,
            'batch_id': self.batch_id,
            'project_id': self.project_id,
            'name': self.name,
            'subject': self.subject,
            'html_body': self.html_body,
            'text_body': self.text_body,
            'pretext_category': self.pretext_category,
            'target_roles': self.parsed_target_roles,
            'sender_suggestion': self.sender_suggestion,
            'relevance_score': self.relevance_score,
            'notes': self.notes,
            'gophish_template_id': self.gophish_template_id,
            'pushed_at': self.pushed_at.isoformat() if self.pushed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
