from app import db
from datetime import datetime


class DomainGroomingTag(db.Model):
    __tablename__ = 'domain_grooming_tags'

    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domains.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    tag = db.Column(db.String(50), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('domain_id', 'tag', name='uq_domain_grooming_tag'),
    )

    domain = db.relationship('Domain', back_populates='grooming_tags_rel')

    def __repr__(self):
        return f'<DomainGroomingTag domain_id={self.domain_id} tag={self.tag}>'
