import os
from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file, current_app, abort
from flask_login import login_required, current_user
from app.extensions import db, get_client_ip
from app.utils.decorators import admin_required
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization
from app.models.request import BloodRequest
from app.models.inventory import BloodInventory
from app.models.donation import Donation
from app.models.rewards import Coupon
from app.models.audit import AuditLog
from app.models.verification import VerificationApplication, VerificationDocument
from app.matching.prioritization import update_request_priority
from app.matching.engine import run_donor_matching
from app.notifications.services import create_notification

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
@login_required
@admin_required
def enforce_admin_role():
    pass


@admin_bp.route('/dashboard')
def dashboard():
    total_donors = User.query.filter_by(role='DONOR').count()
    total_hospitals = Organization.query.filter_by(organization_type='HOSPITAL').count()
    total_banks = Organization.query.filter_by(organization_type='BLOOD_BANK').count()

    pending_orgs = Organization.query.filter_by(verification_status='PENDING').count()
    pending_requests = BloodRequest.query.filter_by(verification_status='PENDING').count()
    active_verified_requests = BloodRequest.query.filter(
        BloodRequest.verification_status == 'VERIFIED',
        BloodRequest.request_status.in_(['VERIFIED', 'MATCHING'])
    ).count()

    recent_audits = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10).all()

    return render_template(
        'admin/dashboard.html',
        total_donors=total_donors,
        total_hospitals=total_hospitals,
        total_banks=total_banks,
        pending_orgs=pending_orgs,
        pending_requests=pending_requests,
        active_verified_requests=active_verified_requests,
        recent_audits=recent_audits
    )


@admin_bp.route('/donors')
def donors():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    blood_group_filter = request.args.get('blood_group', '').strip().upper()
    state_filter = request.args.get('state', '').strip()
    availability_filter = request.args.get('availability', '').strip().upper()

    query = DonorProfile.query.join(User, DonorProfile.user_id == User.id)

    if blood_group_filter:
        query = query.filter(DonorProfile.declared_blood_group == blood_group_filter)

    if state_filter:
        query = query.filter(DonorProfile.state == state_filter)

    if availability_filter == 'AVAILABLE':
        query = query.filter(DonorProfile.availability_status.is_(True))
    elif availability_filter == 'UNAVAILABLE':
        query = query.filter(DonorProfile.availability_status.is_(False))

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern),
                DonorProfile.city.ilike(search_pattern),
                DonorProfile.district.ilike(search_pattern),
                DonorProfile.phone.ilike(search_pattern)
            )
        )

    donors_pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=15)

    from app.locations import get_all_states
    return render_template(
        'admin/donors.html',
        pagination=donors_pagination,
        donors=donors_pagination.items,
        search=search,
        selected_bg=blood_group_filter,
        selected_state=state_filter,
        selected_availability=availability_filter,
        all_states=get_all_states()
    )


@admin_bp.route('/organizations')
def organizations():
    status_filter = request.args.get('status', 'PENDING')
    query = Organization.query
    if status_filter != 'ALL':
        query = query.filter_by(verification_status=status_filter)

    orgs = query.order_by(Organization.created_at.desc()).all()

    return render_template(
        'admin/organizations.html',
        organizations=orgs,
        current_filter=status_filter
    )


@admin_bp.route('/organizations/<int:org_id>/verify', methods=['POST'])
def verify_organization(org_id):
    org = Organization.query.get_or_404(org_id)
    try:
        org.verification_status = 'VERIFIED'
        org.updated_at = datetime.now(timezone.utc)

        AuditLog.log(
            action='VERIFY_ORGANIZATION',
            entity_type='Organization',
            entity_id=org.id,
            details=f"Approved verification for {org.organization_name} ({org.organization_type})",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )

        db.session.commit()

        # Notify representative
        for membership in org.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='ORG_VERIFIED',
                title='Organization Approved!',
                message=f"Congratulations! {org.organization_name} has been verified by administrators. Trusted operations are now enabled."
            )

        flash(f"Organization '{org.organization_name}' has been verified successfully.", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Admin Verify Org Error]: {e}")
        flash("Database error occurred while verifying organization.", "danger")

    return redirect(url_for('admin.organizations'))


@admin_bp.route('/organizations/<int:org_id>/reject', methods=['POST'])
def reject_organization(org_id):
    org = Organization.query.get_or_404(org_id)
    try:
        org.verification_status = 'REJECTED'
        org.updated_at = datetime.now(timezone.utc)

        AuditLog.log(
            action='REJECT_ORGANIZATION',
            entity_type='Organization',
            entity_id=org.id,
            details=f"Rejected verification for {org.organization_name}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )

        db.session.commit()

        for membership in org.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='ORG_REJECTED',
                title='Organization Verification Rejected',
                message=f"Verification for {org.organization_name} was rejected. Please contact administrator support with valid documentation."
            )

        flash(f"Organization '{org.organization_name}' has been marked as REJECTED.", "warning")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Admin Reject Org Error]: {e}")
        flash("Database error occurred while rejecting organization.", "danger")

    return redirect(url_for('admin.organizations'))


@admin_bp.route('/verifications')
def verifications():
    """Registration Verification Center: dedicated tabs for Donors, Hospitals, Blood Banks, Approved, Rejected, Suspended."""
    active_tab = request.args.get('tab', 'hospitals')

    pending_donors = DonorProfile.query.filter(
        DonorProfile.verification_status.in_(['PENDING', 'PENDING_VERIFICATION'])
    ).all()

    pending_hospitals = Organization.query.filter_by(
        organization_type='HOSPITAL',
        verification_status='PENDING'
    ).order_by(Organization.created_at.desc()).all()

    pending_banks = Organization.query.filter_by(
        organization_type='BLOOD_BANK',
        verification_status='PENDING'
    ).order_by(Organization.created_at.desc()).all()

    approved_orgs = Organization.query.filter(
        Organization.verification_status.in_(['VERIFIED', 'APPROVED'])
    ).order_by(Organization.updated_at.desc()).all()

    rejected_applications = Organization.query.filter_by(
        verification_status='REJECTED'
    ).order_by(Organization.updated_at.desc()).all()

    suspended_accounts = Organization.query.filter_by(
        verification_status='SUSPENDED'
    ).order_by(Organization.updated_at.desc()).all()

    applications = VerificationApplication.query.order_by(
        VerificationApplication.submitted_at.desc()
    ).limit(50).all()

    return render_template(
        'admin/verifications.html',
        active_tab=active_tab,
        pending_donors=pending_donors,
        pending_hospitals=pending_hospitals,
        pending_banks=pending_banks,
        approved_orgs=approved_orgs,
        rejected_applications=rejected_applications,
        suspended_accounts=suspended_accounts,
        applications=applications
    )


@admin_bp.route('/verifications/organization/<int:org_id>/approve', methods=['POST'])
def approve_organization_verification(org_id):
    """Transactionally approve hospital or blood bank registration with canonical VERIFIED status."""
    if not current_user.is_authenticated or current_user.role != 'ADMIN':
        abort(403)

    org = Organization.query.get_or_404(org_id)
    review_method = request.form.get('review_method', 'MANUAL_DOCUMENT_REVIEW').strip()

    # Prevent duplicate approval operations
    if org.verification_status == 'VERIFIED':
        flash(f"Facility '{org.organization_name}' has already been verified and approved.", "info")
        return redirect(url_for('admin.verifications', tab='approved'))

    # Prevent ordinary self-approval if admin is affiliated with this facility and other admins exist
    affiliated_membership = org.memberships.filter_by(user_id=current_user.id).first()
    if affiliated_membership and User.query.filter_by(role='ADMIN').count() > 1:
        flash("Compliance policy: Administrators cannot approve facility registrations to which their personal account is affiliated.", "danger")
        return redirect(url_for('admin.verifications', tab='hospitals' if org.organization_type == 'HOSPITAL' else 'banks'))

    try:
        # Set canonical status in database
        org.verification_status = 'VERIFIED'
        org.updated_at = datetime.now(timezone.utc)

        # Synchronize and record VerificationApplication regulatory audit details
        apps = VerificationApplication.query.filter_by(organization_id=org.id).all()
        if apps:
            for app_rec in apps:
                app_rec.verification_status = 'APPROVED'
                app_rec.reviewer_id = current_user.id
                app_rec.reviewed_at = datetime.now(timezone.utc)
                app_rec.verification_method = review_method
                app_rec.review_reason = f"Approved and accredited by administrator {current_user.name}"
        else:
            rep_membership = org.memberships.first()
            if rep_membership:
                app_rec = VerificationApplication(
                    user_id=rep_membership.user_id,
                    organization_id=org.id,
                    verification_type=org.organization_type,
                    verification_status='APPROVED',
                    verification_method=review_method,
                    provider_reference=org.registration_reference,
                    reviewer_id=current_user.id,
                    reviewed_at=datetime.now(timezone.utc),
                    review_reason=f"Approved and accredited by administrator {current_user.name}"
                )
                db.session.add(app_rec)

        AuditLog.log(
            action='APPROVE_VERIFICATION',
            entity_type='Organization',
            entity_id=org.id,
            details=f"Approved {org.organization_name} ({org.organization_type}) via {review_method}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()

        for membership in org.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='ORG_VERIFIED',
                title='Registration Approved!',
                message=f"Congratulations! {org.organization_name} has been verified and approved by platform administrators. Operational clinical privileges are now activated."
            )

        flash(f"Facility '{org.organization_name}' has been successfully APPROVED.", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Approve Org Error]: {e}")
        flash("Database error occurred while approving facility.", "danger")

    return redirect(url_for('admin.verifications', tab='approved'))


@admin_bp.route('/verifications/organization/<int:org_id>/reject', methods=['POST'])
def reject_organization_verification(org_id):
    """Reject hospital or blood bank registration with mandatory explanation."""
    if not current_user.is_authenticated or current_user.role != 'ADMIN':
        abort(403)

    org = Organization.query.get_or_404(org_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash("Rejection requires a documented justification reason.", "warning")
        return redirect(url_for('admin.verifications', tab='hospitals' if org.organization_type == 'HOSPITAL' else 'banks'))

    # Prevent duplicate rejection operations
    if org.verification_status == 'REJECTED':
        flash(f"Facility '{org.organization_name}' is already rejected.", "info")
        return redirect(url_for('admin.verifications', tab='rejected'))

    try:
        org.verification_status = 'REJECTED'
        org.updated_at = datetime.now(timezone.utc)

        # Synchronize and record VerificationApplication regulatory audit details
        apps = VerificationApplication.query.filter_by(organization_id=org.id).all()
        if apps:
            for app_rec in apps:
                app_rec.verification_status = 'REJECTED'
                app_rec.reviewer_id = current_user.id
                app_rec.reviewed_at = datetime.now(timezone.utc)
                app_rec.review_reason = reason
        else:
            rep_membership = org.memberships.first()
            if rep_membership:
                app_rec = VerificationApplication(
                    user_id=rep_membership.user_id,
                    organization_id=org.id,
                    verification_type=org.organization_type,
                    verification_status='REJECTED',
                    verification_method='MANUAL_DOCUMENT_REVIEW',
                    provider_reference=org.registration_reference,
                    reviewer_id=current_user.id,
                    reviewed_at=datetime.now(timezone.utc),
                    review_reason=reason
                )
                db.session.add(app_rec)

        AuditLog.log(
            action='REJECT_VERIFICATION',
            entity_type='Organization',
            entity_id=org.id,
            details=f"Rejected {org.organization_name} ({org.organization_type}). Reason: {reason}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()

        for membership in org.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='ORG_REJECTED',
                title='Application Rejected',
                message=f"Application for {org.organization_name} was rejected: {reason}. You may resubmit credentials through administrative support."
            )

        flash(f"Facility '{org.organization_name}' has been marked as REJECTED.", "warning")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Reject Org Error]: {e}")
        flash("Database error occurred while rejecting facility.", "danger")

    return redirect(url_for('admin.verifications', tab='rejected'))


@admin_bp.route('/verifications/organization/<int:org_id>/request-docs', methods=['POST'])
def request_organization_docs(org_id):
    """Request additional licensing or regulatory documentation from applicant."""
    org = Organization.query.get_or_404(org_id)
    notes = request.form.get('notes', '').strip() or "Additional licensing documentation required"

    try:
        org.verification_status = 'PENDING'
        org.updated_at = datetime.now(timezone.utc)

        AuditLog.log(
            action='REQUEST_DOCUMENTATION',
            entity_type='Organization',
            entity_id=org.id,
            details=f"Requested additional documentation for {org.organization_name}: {notes}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()

        for membership in org.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='DOCUMENTATION_REQUESTED',
                title='Additional Documentation Required',
                message=f"Administrator review note for {org.organization_name}: {notes}. Please update registration credentials."
            )

        flash(f"Documentation request dispatched to '{org.organization_name}'.", "info")
    except Exception as e:
        db.session.rollback()
        flash("Could not send documentation request.", "danger")

    return redirect(url_for('admin.verifications', tab='hospitals' if org.organization_type == 'HOSPITAL' else 'banks'))


@admin_bp.route('/verifications/organization/<int:org_id>/suspend', methods=['POST'])
def suspend_organization(org_id):
    """Suspend an approved organization due to compliance or safety concerns."""
    org = Organization.query.get_or_404(org_id)
    reason = request.form.get('reason', '').strip() or "Administrative compliance suspension"

    try:
        org.verification_status = 'SUSPENDED'
        org.updated_at = datetime.now(timezone.utc)

        AuditLog.log(
            action='SUSPEND_ACCOUNT',
            entity_type='Organization',
            entity_id=org.id,
            details=f"Suspended organization {org.organization_name}. Reason: {reason}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()

        for membership in org.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='ACCOUNT_SUSPENDED',
                title='Account Suspended',
                message=f"Facility {org.organization_name} has been suspended: {reason}."
            )

        flash(f"Organization '{org.organization_name}' has been SUSPENDED.", "warning")
    except Exception as e:
        db.session.rollback()
        flash("Could not suspend organization.", "danger")

    return redirect(url_for('admin.verifications', tab='suspended'))


@admin_bp.route('/verifications/organization/<int:org_id>/restore', methods=['POST'])
def restore_organization(org_id):
    """Restore a suspended organization following verified audit review."""
    if not current_user.is_authenticated or current_user.role != 'ADMIN':
        abort(403)

    org = Organization.query.get_or_404(org_id)
    try:
        org.verification_status = 'VERIFIED'
        org.updated_at = datetime.now(timezone.utc)

        # Update verification application records
        apps = VerificationApplication.query.filter_by(organization_id=org.id).all()
        for app_rec in apps:
            app_rec.verification_status = 'APPROVED'
            app_rec.reviewer_id = current_user.id
            app_rec.reviewed_at = datetime.now(timezone.utc)
            app_rec.review_reason = "Restored following verified audit review"

        AuditLog.log(
            action='RESTORE_ACCOUNT',
            entity_type='Organization',
            entity_id=org.id,
            details=f"Restored approved standing for {org.organization_name}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()

        for membership in org.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='ACCOUNT_RESTORED',
                title='Account Restored',
                message=f"Facility {org.organization_name} privileges have been restored."
            )

        flash(f"Organization '{org.organization_name}' restored to APPROVED standing.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Could not restore organization.", "danger")

    return redirect(url_for('admin.verifications', tab='approved'))


@admin_bp.route('/verifications/donor/<int:donor_id>/approve', methods=['POST'])
def approve_donor_verification(donor_id):
    """Approve voluntary donor identity verification."""
    profile = DonorProfile.query.filter_by(user_id=donor_id).first_or_404()
    try:
        profile.verification_status = 'APPROVED'
        profile.updated_at = datetime.now(timezone.utc)

        AuditLog.log(
            action='APPROVE_VERIFICATION',
            entity_type='DonorProfile',
            entity_id=profile.id,
            details=f"Approved identity verification for donor User #{profile.user_id}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()

        create_notification(
            recipient_id=profile.user_id,
            notification_type='DONOR_VERIFIED',
            title='Donor Identity Verified!',
            message="Your donor identity verification has been reviewed and approved by administrators."
        )

        flash(f"Donor '{profile.user.name}' has been APPROVED.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Could not approve donor.", "danger")

    return redirect(url_for('admin.verifications', tab='donors'))


@admin_bp.route('/verifications/donor/<int:donor_id>/reject', methods=['POST'])
def reject_donor_verification(donor_id):
    """Reject voluntary donor identity verification with reason."""
    profile = DonorProfile.query.filter_by(user_id=donor_id).first_or_404()
    reason = request.form.get('reason', '').strip() or "Identity verification documentation could not be confirmed"

    try:
        profile.verification_status = 'REJECTED'
        profile.updated_at = datetime.now(timezone.utc)

        AuditLog.log(
            action='REJECT_VERIFICATION',
            entity_type='DonorProfile',
            entity_id=profile.id,
            details=f"Rejected donor User #{profile.user_id}. Reason: {reason}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()

        create_notification(
            recipient_id=profile.user_id,
            notification_type='DONOR_REJECTED',
            title='Identity Verification Notice',
            message=f"Identity verification notice: {reason}. You may re-submit valid credentials."
        )

        flash(f"Donor '{profile.user.name}' verification marked as REJECTED.", "warning")
    except Exception as e:
        db.session.rollback()
        flash("Could not reject donor.", "danger")

    return redirect(url_for('admin.verifications', tab='rejected'))


@admin_bp.route('/verifications/document/<int:doc_id>/view')
def view_verification_document(doc_id):
    """Protected Document Access: Serves regulatory documents from private storage outside public web directory with audit logging."""
    doc = VerificationDocument.query.get_or_404(doc_id)

    # Isolated Storage Directory
    secure_dir = current_app.config.get('SECURE_DOCUMENTS_DIR')
    if not secure_dir:
        secure_dir = os.path.join(current_app.root_path, '..', 'instance', 'secure_documents')

    file_path = os.path.join(secure_dir, doc.private_storage_reference)
    if not os.path.isfile(file_path):
        flash("The requested verification document was not found or has been securely purged.", "warning")
        return redirect(url_for('admin.verifications'))

    # Security Audit: Record document access
    AuditLog.log(
        action='ACCESS_VERIFICATION_DOCUMENT',
        entity_type='VerificationDocument',
        entity_id=doc.id,
        details=f"Admin {current_user.email} accessed document #{doc.id} ({doc.document_type})",
        actor_id=current_user.id,
        ip_address=get_client_ip()
    )
    db.session.commit()

    return send_file(file_path, as_attachment=False)


@admin_bp.route('/requests')
def requests():
    status_filter = request.args.get('status', 'ALL')
    query = BloodRequest.query
    if status_filter == 'PENDING':
        query = query.filter_by(verification_status='PENDING')
    elif status_filter == 'FLAGGED':
        query = query.filter_by(request_status='FLAGGED_FOR_REVIEW')
    elif status_filter == 'ACTIVE':
        query = query.filter(BloodRequest.request_status.notin_(['FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'FLAGGED_FOR_REVIEW', 'VALIDATION_FAILED']))
    elif status_filter == 'FULFILLED':
        query = query.filter_by(request_status='FULFILLED')
    elif status_filter != 'ALL':
        query = query.filter_by(verification_status=status_filter)

    reqs = query.order_by(BloodRequest.priority_score.desc()).all()

    from app.models.communication import BloodBankResponse, DonorRequestResponse
    from app.models.donation import Donation
    from app.models.donor import DonorProfile
    from datetime import date

    total_requests_count = BloodRequest.query.count()
    active_requests_count = BloodRequest.query.filter(
        BloodRequest.request_status.notin_(['FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'FLAGGED_FOR_REVIEW', 'VALIDATION_FAILED'])
    ).count()
    flagged_count = BloodRequest.query.filter_by(request_status='FLAGGED_FOR_REVIEW').count()
    verified_donations_count = Donation.query.filter_by(verification_status='VERIFIED').count()
    donors_in_recovery_count = DonorProfile.query.filter(
        DonorProfile.next_eligible_date.isnot(None),
        DonorProfile.next_eligible_date > date.today()
    ).count()

    metrics = {
        'total': total_requests_count,
        'active': active_requests_count,
        'flagged': flagged_count,
        'verified_donations': verified_donations_count,
        'in_recovery': donors_in_recovery_count
    }

    return render_template(
        'admin/requests.html',
        requests=reqs,
        current_filter=status_filter,
        metrics=metrics
    )


@admin_bp.route('/requests/<int:req_id>/verify', methods=['POST'])
def verify_request(req_id):
    req = BloodRequest.query.get_or_404(req_id)
    try:
        req.verification_status = 'VERIFIED'
        req.request_status = 'ACTIVE_MATCHING'
        req.updated_at = datetime.now(timezone.utc)

        # Recalculate trusted priority
        update_request_priority(req)

        AuditLog.log(
            action='VERIFY_BLOOD_REQUEST',
            entity_type='BloodRequest',
            entity_id=req.id,
            details=f"Admin verified request {req.request_reference} (Priority: {req.priority_score})",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )

        db.session.commit()

        # Trigger smart donor matching and notifications automatically
        matches = run_donor_matching(req, notify_donors=True)

        flash(f"Request {req.request_reference} verified! Preliminary Smart Matching dispatched to {len(matches)} suitable donors.", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Admin Verify Request Error]: {e}")
        flash("Database error occurred while verifying blood request.", "danger")

    return redirect(url_for('admin.requests'))


@admin_bp.route('/requests/<int:req_id>/flag', methods=['POST'])
def flag_request(req_id):
    """Allows administrators to flag a suspicious or non-compliant request for investigation."""
    req = BloodRequest.query.get_or_404(req_id)
    reason = request.form.get('reason', '').strip() or "Administrative compliance review"

    try:
        req.request_status = 'FLAGGED_FOR_REVIEW'
        req.updated_at = datetime.now(timezone.utc)

        AuditLog.log(
            action='FLAG_BLOOD_REQUEST',
            entity_type='BloodRequest',
            entity_id=req.id,
            details=f"Admin flagged request {req.request_reference}. Reason: {reason}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )

        # Notify requesting hospital
        for membership in req.requesting_organization.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='REQUEST_FLAGGED',
                title='Request Flagged for Administrative Review',
                message=f"Request {req.request_reference} has been placed on hold for administrative review: {reason}."
            )

        db.session.commit()
        flash(f"Request {req.request_reference} has been FLAGGED for administrative investigation.", "warning")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Admin Flag Request Error]: {e}")
        flash("Could not flag request at this time.", "danger")

    return redirect(url_for('admin.requests'))


@admin_bp.route('/requests/<int:req_id>/unflag', methods=['POST'])
def unflag_request(req_id):
    """Allows administrators to resolve an investigation and restore a request to active matching."""
    req = BloodRequest.query.get_or_404(req_id)
    try:
        req.request_status = 'ACTIVE_MATCHING'
        req.verification_status = 'VERIFIED'
        req.updated_at = datetime.now(timezone.utc)

        update_request_priority(req)

        AuditLog.log(
            action='UNFLAG_BLOOD_REQUEST',
            entity_type='BloodRequest',
            entity_id=req.id,
            details=f"Admin cleared investigation and restored request {req.request_reference}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )

        # Re-trigger donor matching
        matches = run_donor_matching(req, notify_donors=True)

        for membership in req.requesting_organization.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='REQUEST_RESTORED',
                title='Request Restored to Active Matching',
                message=f"Administrative review for request {req.request_reference} has been completed and cleared. Active matching is resumed."
            )

        db.session.commit()
        flash(f"Request {req.request_reference} investigation cleared and restored to ACTIVE MATCHING.", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Admin Unflag Request Error]: {e}")
        flash("Could not restore request at this time.", "danger")

    return redirect(url_for('admin.requests'))


@admin_bp.route('/requests/<int:req_id>/reject', methods=['POST'])
def reject_request(req_id):
    req = BloodRequest.query.get_or_404(req_id)
    try:
        req.verification_status = 'REJECTED'
        req.request_status = 'REJECTED'
        req.updated_at = datetime.now(timezone.utc)

        AuditLog.log(
            action='REJECT_BLOOD_REQUEST',
            entity_type='BloodRequest',
            entity_id=req.id,
            details=f"Rejected request {req.request_reference}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )

        db.session.commit()
        flash(f"Request {req.request_reference} has been rejected.", "warning")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Admin Reject Request Error]: {e}")
        flash("Database error occurred while rejecting request.", "danger")

    return redirect(url_for('admin.requests'))


@admin_bp.route('/coupons', methods=['GET', 'POST'])
def coupons():
    if request.method == 'POST':
        partner_name = request.form.get('partner_name', '').strip()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', 'Healthcare').strip()
        points_required = int(request.form.get('points_required', 100))
        icon = request.form.get('icon', 'bi-gift').strip()

        if partner_name and title and points_required > 0:
            try:
                coupon = Coupon(
                    partner_name=partner_name,
                    title=title,
                    description=description,
                    category=category,
                    points_required=points_required,
                    icon=icon,
                    coupon_status='ACTIVE'
                )
                db.session.add(coupon)
                AuditLog.log(action='CREATE_COUPON', entity_type='Coupon', details=f"Added coupon: {title}", actor_id=current_user.id, ip_address=get_client_ip())
                db.session.commit()
                flash(f"Coupon perk '{title}' added to the marketplace.", "success")
            except Exception as e:
                db.session.rollback()
                import logging
                logging.getLogger(__name__).error(f"[Admin Coupon Error]: {e}")
                flash("Database error occurred while creating coupon.", "danger")

        return redirect(url_for('admin.coupons'))

    all_coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
    return render_template('admin/coupons.html', coupons=all_coupons)


@admin_bp.route('/analytics')
def analytics():
    return render_template('admin/analytics.html')


@admin_bp.route('/audit-logs')
def audit_logs():
    page = request.args.get('page', 1, type=int)
    logs_pagination = AuditLog.query.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('admin/audit_logs.html', pagination=logs_pagination)


@admin_bp.route('/users')
def users():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '').strip().upper()
    status_filter = request.args.get('status', '').strip().upper()

    query = User.query

    if role_filter in ['DONOR', 'HOSPITAL', 'BLOOD_BANK', 'ADMIN']:
        query = query.filter_by(role=role_filter)

    now_utc = datetime.now(timezone.utc)
    if status_filter == 'ACTIVE':
        query = query.filter(User.is_active.is_(True))
    elif status_filter == 'SUSPENDED':
        query = query.filter(User.is_active.is_(False))
    elif status_filter == 'LOCKED':
        query = query.filter(User.locked_until.isnot(None), User.locked_until > now_utc)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern)
            )
        )

    users_pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=15)

    return render_template(
        'admin/users.html',
        pagination=users_pagination,
        users=users_pagination.items,
        search=search,
        selected_role=role_filter,
        selected_status=status_filter,
        now_utc=now_utc
    )


@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
def toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("You cannot suspend your own administrator account.", "danger")
        return redirect(request.referrer or url_for('admin.users'))

    reason = request.form.get('reason', '').strip() or "Administrative action"
    user.is_active = not user.is_active
    new_state = "Active" if user.is_active else "Suspended"
    action = "REACTIVATE_ACCOUNT" if user.is_active else "SUSPEND_ACCOUNT"

    try:
        AuditLog.log(
            action=action,
            entity_type='User',
            entity_id=user.id,
            details=f"Account status updated to {new_state}. Reason: {reason}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()
        flash(f"User '{user.name}' ({user.email}) has been marked as {new_state}.", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Admin Toggle User Status Error]: {e}")
        flash("Database error occurred while updating user status.", "danger")

    return redirect(request.referrer or url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/unlock', methods=['POST'])
def unlock_user(user_id):
    user = User.query.get_or_404(user_id)
    reason = request.form.get('reason', '').strip() or "Manual administrator unlock"

    try:
        user.locked_until = None
        user.failed_login_attempts = 0
        AuditLog.log(
            action='UNLOCK_ACCOUNT',
            entity_type='User',
            entity_id=user.id,
            details=f"Account brute-force lockout cleared. Reason: {reason}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()
        flash(f"Brute-force lockout cleared for user '{user.name}' ({user.email}).", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Admin Unlock User Error]: {e}")
        flash("Database error occurred while unlocking account.", "danger")

    return redirect(request.referrer or url_for('admin.users'))



# ==========================================
# REST Analytics Endpoints for Chart.js
# ==========================================

@admin_bp.route('/api/analytics/blood-groups')
def api_analytics_blood_groups():
    groups = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
    data = []
    for g in groups:
        count = BloodRequest.query.filter_by(blood_group=g).count()
        data.append(count)
    return jsonify({'labels': groups, 'data': data})


@admin_bp.route('/api/analytics/inventory')
def api_analytics_inventory():
    components = ['Whole Blood', 'Red Blood Cells', 'Platelets', 'Plasma']
    data = []
    for comp in components:
        units = db.session.query(db.func.coalesce(db.func.sum(BloodInventory.available_units), 0))\
            .filter_by(component_type=comp).scalar() or 0
        data.append(units)
    return jsonify({'labels': components, 'data': data})


@admin_bp.route('/api/analytics/states-distribution')
def api_analytics_states_distribution():
    donor_counts = db.session.query(DonorProfile.state, db.func.count(DonorProfile.id))\
        .filter(DonorProfile.state.isnot(None))\
        .group_by(DonorProfile.state)\
        .order_by(db.func.count(DonorProfile.id).desc())\
        .limit(8).all()

    org_counts = db.session.query(Organization.state, db.func.count(Organization.id))\
        .filter(Organization.state.isnot(None))\
        .group_by(Organization.state)\
        .order_by(db.func.count(Organization.id).desc())\
        .limit(8).all()

    return jsonify({
        'donors': {
            'labels': [row[0] for row in donor_counts],
            'data': [row[1] for row in donor_counts]
        },
        'organizations': {
            'labels': [row[0] for row in org_counts],
            'data': [row[1] for row in org_counts]
        }
    })


@admin_bp.route('/api/analytics/request-urgency')
def api_analytics_request_urgency():
    urgency_counts = db.session.query(BloodRequest.urgency_level, db.func.count(BloodRequest.id))\
        .group_by(BloodRequest.urgency_level).all()
    order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    counts_dict = {row[0]: row[1] for row in urgency_counts}
    labels = [lvl for lvl in order if lvl in counts_dict]
    for lvl in counts_dict:
        if lvl not in labels:
            labels.append(lvl)
    data = [counts_dict.get(lvl, 0) for lvl in labels]
    return jsonify({'labels': labels, 'data': data})
