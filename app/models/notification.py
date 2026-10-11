from datetime import datetime, timezone
from app.extensions import db


class Notification(db.Model):
    """In-app alerts and delivery records for donors, hospitals, and blood banks."""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    @property
    def is_read(self):
        return self.read_at is not None

    def mark_as_read(self):
        self.read_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f'<Notification Recipient={self.recipient_id} Type={self.notification_type}>'
