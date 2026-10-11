import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from app.extensions import db
from app.models.notification import Notification
from app.models.user import User


def create_notification(recipient_id: int, notification_type: str, title: str, message: str) -> Notification:
    """Create a trusted in-app notification for a user and trigger optional email alert."""
    # Deduplication check: Prevent duplicate notifications sent to the same user within 3 minutes
    from datetime import timedelta
    recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)
    existing = Notification.query.filter(
        Notification.recipient_id == recipient_id,
        Notification.notification_type == notification_type,
        Notification.title == title,
        Notification.created_at >= recent_cutoff
    ).first()
    if existing:
        return existing

    notification = Notification(
        recipient_id=recipient_id,
        notification_type=notification_type,
        title=title,
        message=message,
        created_at=datetime.now(timezone.utc)
    )

    try:
        db.session.add(notification)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).warning(f"[Notification Persistence Warning]: {e}")
        return None

    # Optional Email notification if configured in environment and not a demo account
    try:
        recipient = db.session.get(User, recipient_id)
        if recipient and recipient.email and not getattr(recipient, 'is_demo', False):
            _send_email_notification(recipient.email, title, message)
    except Exception:
        pass

    return notification


def _send_email_notification(to_email: str, subject: str, message_body: str):
    """Attempt email dispatch if SMTP environment variables are present."""
    smtp_server = os.environ.get('SMTP_SERVER')
    smtp_port = os.environ.get('SMTP_PORT')
    smtp_user = os.environ.get('SMTP_USERNAME')
    smtp_pass = os.environ.get('SMTP_PASSWORD')

    # If email credentials are not configured, gracefully omit without pretending delivery
    if not (smtp_server and smtp_user and smtp_pass):
        return False

    try:
        port = int(smtp_port or 587)
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = f"[BloodLink AI] {subject}"
        msg.attach(MIMEText(message_body, 'plain'))

        with smtplib.SMTP(smtp_server, port, timeout=5) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception as e:
        # Log delivery issue without disrupting application flow
        print(f"[Email Notification Error]: Failed sending to {to_email}: {e}")
        return False
