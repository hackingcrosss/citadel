import json
from app import db
from datetime import datetime


class IAFofaSearch(db.Model):
    __tablename__ = 'ia_fofa_searches'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    search_query = db.Column('query', db.Text, nullable=False)
    scope_type = db.Column(db.String(20))       # domain, ip, cidr, custom
    scope_value = db.Column(db.String(500))
    total_results = db.Column(db.Integer)        # FOFA reported total
    results_count = db.Column(db.Integer)        # actual rows stored
    raw_results = db.Column(db.Text)             # JSON array of result dicts
    status = db.Column(db.String(20), nullable=False, default='pending')
    error_message = db.Column(db.Text)
    searched_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', foreign_keys=[project_id])
    searched_by = db.relationship('User', foreign_keys=[searched_by_id])

    def to_dict(self, include_results=False):
        d = {
            'id': self.id,
            'project_id': self.project_id,
            'query': self.search_query,
            'scope_type': self.scope_type,
            'scope_value': self.scope_value,
            'total_results': self.total_results,
            'results_count': self.results_count,
            'status': self.status,
            'error_message': self.error_message,
            'searched_by': self.searched_by.display_name if self.searched_by else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_results and self.raw_results:
            d['results'] = json.loads(self.raw_results)
        return d
