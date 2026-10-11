from datetime import datetime, timezone
import markupsafe
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db, limiter, get_client_ip
from app.models.communication import Conversation, Message, DonorRequestResponse, DonorInvitation
from app.models.request import BloodRequest
from app.models.user import User
from app.models.audit import AuditLog
from app.notifications.services import create_notification

communication_bp = Blueprint('communication', __name__, url_prefix='/communication')


@communication_bp.before_request
@login_required
def enforce_authenticated_user():
    """Ensure user is logged in and active before accessing communication services."""
    if not current_user.is_authenticated or not current_user.is_active:
        abort(403)


@communication_bp.route('/conversations')
def list_conversations():
    """List all active message exchanges for the authenticated user."""
    if current_user.role == 'DONOR':
        conversations = Conversation.query.filter_by(donor_id=current_user.id)\
            .order_by(Conversation.updated_at.desc()).all()
    elif current_user.role == 'HOSPITAL':
        org = current_user.organization
        if not org:
            flash("No hospital facility linked to your account.", "danger")
            return redirect(url_for('main.index'))
        conversations = Conversation.query.filter_by(hospital_id=org.id)\
            .order_by(Conversation.updated_at.desc()).all()
    elif current_user.role == 'ADMIN':
        conversations = Conversation.query.order_by(Conversation.updated_at.desc()).limit(100).all()
    else:
        abort(403)

    return render_template('communication/conversations.html', conversations=conversations)


@communication_bp.route('/conversation/<int:conversation_id>')
def view_conversation(conversation_id):
    """View messages in an authorized conversation and mark unread incoming messages as read."""
    conv = Conversation.query.get_or_404(conversation_id)

    # IDOR Defense: verify current user is a valid participant or platform admin
    if not conv.is_participant(current_user):
        AuditLog.log(
            action='UNAUTHORIZED_MESSAGE_ACCESS_ATTEMPT',
            entity_type='Conversation',
            entity_id=conv.id,
            details=f"User {current_user.id} denied access to conversation {conv.id}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        abort(403)

    # Mark incoming unread messages as read
    try:
        updated = False
        for msg in conv.messages:
            if msg.sender_user_id != current_user.id and not msg.is_read:
                msg.mark_read()
                updated = True
        if updated:
            db.session.commit()
    except Exception:
        db.session.rollback()

    messages = conv.messages.all()

    return render_template(
        'communication/conversation.html',
        conv=conv,
        messages=messages
    )


@communication_bp.route('/conversation/<int:conversation_id>/send', methods=['POST'])
@limiter.limit("20 per minute")
def send_message(conversation_id):
    """Submit a secure message within an authorized clinical conversation."""
    conv = Conversation.query.get_or_404(conversation_id)

    if not conv.is_participant(current_user):
        abort(403)

    raw_body = request.form.get('message_body', '').strip()
    if not raw_body:
        flash("Message content cannot be blank.", "warning")
        return redirect(url_for('communication.view_conversation', conversation_id=conv.id))

    if len(raw_body) > 1500:
        flash("Message exceeds maximum permitted length of 1,500 characters.", "warning")
        return redirect(url_for('communication.view_conversation', conversation_id=conv.id))

    # XSS Protection: HTML escape user-generated input
    safe_body = str(markupsafe.escape(raw_body))

    try:
        new_msg = Message(
            conversation_id=conv.id,
            sender_user_id=current_user.id,
            message_body=safe_body,
            created_at=datetime.now(timezone.utc)
        )
        conv.updated_at = datetime.now(timezone.utc)
        db.session.add(new_msg)
        db.session.commit()

        # In-App Notification to recipient
        if current_user.id == conv.donor_id:
            # Donor sent message -> notify hospital staff
            for membership in conv.hospital.memberships:
                create_notification(
                    recipient_id=membership.user_id,
                    notification_type='NEW_MESSAGE',
                    title='New Message from Donor',
                    message=f"Donor {current_user.name} sent a message regarding blood request {conv.blood_request.request_reference}."
                )
        else:
            # Hospital staff sent message -> notify donor
            create_notification(
                recipient_id=conv.donor_id,
                notification_type='NEW_MESSAGE',
                title='New Message from Hospital',
                message=f"{conv.hospital.organization_name} sent a message regarding blood request {conv.blood_request.request_reference}."
            )

        AuditLog.log(
            action='SEND_MESSAGE',
            entity_type='Conversation',
            entity_id=conv.id,
            details=f"Message sent in conversation {conv.id}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Messaging Error]: {e}")
        flash("Unable to send message at this time. Please try again.", "danger")

    return redirect(url_for('communication.view_conversation', conversation_id=conv.id))


@communication_bp.route('/message/<int:message_id>/report', methods=['POST'])
def report_message(message_id):
    """Allows participants to flag inappropriate or abusive coordination messages."""
    msg = Message.query.get_or_404(message_id)
    conv = msg.conversation

    if not conv.is_participant(current_user):
        abort(403)

    reason = request.form.get('reason', '').strip() or "Inappropriate or suspicious message content"

    try:
        msg.is_reported = True
        msg.report_reason = reason[:250]
        AuditLog.log(
            action='REPORT_MESSAGE',
            entity_type='Message',
            entity_id=msg.id,
            details=f"Message #{msg.id} reported by User #{current_user.id}. Reason: {reason[:200]}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()
        flash("The message has been reported for administrative safety review.", "info")
    except Exception:
        db.session.rollback()
        flash("Could not submit report at this time.", "danger")

    return redirect(url_for('communication.view_conversation', conversation_id=conv.id))


@communication_bp.route('/start/<int:request_id>/<int:donor_id>', methods=['GET', 'POST'])
def start_or_get_conversation(request_id, donor_id):
    """Finds or starts a conversation between authorized hospital and donor for a blood request."""
    req = BloodRequest.query.get_or_404(request_id)
    donor = User.query.get_or_404(donor_id)

    # Authorization Check
    is_authorized = False
    if current_user.role == 'ADMIN':
        is_authorized = True
    elif current_user.role == 'HOSPITAL':
        org = current_user.organization
        if org and org.id == req.requesting_organization_id:
            is_authorized = True
    elif current_user.role == 'DONOR' and current_user.id == donor_id:
        is_authorized = True

    if not is_authorized:
        abort(403)

    conv = Conversation.query.filter_by(
        blood_request_id=req.id,
        donor_id=donor.id,
        hospital_id=req.requesting_organization_id
    ).first()

    if not conv:
        try:
            conv = Conversation(
                blood_request_id=req.id,
                donor_id=donor.id,
                hospital_id=req.requesting_organization_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.session.add(conv)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Could not initiate conversation channel.", "danger")
            return redirect(request.referrer or url_for('main.index'))

    return redirect(url_for('communication.view_conversation', conversation_id=conv.id))
