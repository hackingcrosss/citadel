from app import db
from datetime import datetime


SCAN_STATUSES = ('pending', 'running', 'completed', 'failed')


class IAScanJob(db.Model):
    __tablename__ = 'ia_scan_jobs'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    external_job_id = db.Column(db.String(255), index=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    target_scope = db.Column(db.Text)       # JSON: {domains:[], ip_ranges:[], orgs:[]}
    results_summary = db.Column(db.Text)    # JSON: aggregated stats
    raw_results = db.Column(db.Text)        # JSON: full result blob
    error_message = db.Column(db.Text)
    triggered_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    triggered_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    polled_at = db.Column(db.DateTime)

    project = db.relationship('Project', foreign_keys=[project_id])
    triggered_by = db.relationship('User', foreign_keys=[triggered_by_id])

    def to_dict(self, include_raw=False):
        import json
        d = {
            'id': self.id,
            'project_id': self.project_id,
            'external_job_id': self.external_job_id,
            'status': self.status,
            'target_scope': json.loads(self.target_scope) if self.target_scope else None,
            'results_summary': json.loads(self.results_summary) if self.results_summary else None,
            'error_message': self.error_message,
            'triggered_by': self.triggered_by.display_name if self.triggered_by else None,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'polled_at': self.polled_at.isoformat() if self.polled_at else None,
        }
        if include_raw and self.raw_results:
            d['raw_results'] = json.loads(self.raw_results)
        return d
