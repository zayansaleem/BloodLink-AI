from datetime import datetime, timezone
from app.extensions import db


class AuditLog(db.Model):
    """Audit trail recording administrative approvals, inventory alterations, and verifications."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    @staticmethod
    def log(action: str, entity_type: str, entity_id: int = None, details: str = None, actor_id: int = None, ip_address: str = None):
        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address
        )
        db.session.add(entry)

    def __repr__(self):
        return f'<AuditLog Actor={self.actor_id} Action={self.action} Entity={self.entity_type}:{self.entity_id}>'
