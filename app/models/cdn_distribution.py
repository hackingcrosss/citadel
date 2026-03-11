from app import db
from datetime import datetime


class CdnDistribution(db.Model):
    __tablename__ = 'cdn_distributions'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False)          # 'cloudfront' | 'azure_front_door'
    account_label = db.Column(db.String(100), nullable=False, default='default')
    external_id = db.Column(db.String(500))                      # CF dist ID or 'rg/profile/endpoint'
    domain = db.Column(db.String(500))                           # *.cloudfront.net or *.azurefd.net
    origin_host = db.Column(db.String(500))                      # IP/hostname of origin server
    origin_port = db.Column(db.Integer, default=443)
    status = db.Column(db.String(50), default='deploying')       # deploying|deployed|disabled|error
    comment = db.Column(db.Text)                                 # links to CS listener name
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'account_label': self.account_label,
            'external_id': self.external_id,
            'domain': self.domain,
            'origin_host': self.origin_host,
            'origin_port': self.origin_port,
            'status': self.status,
            'comment': self.comment,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
