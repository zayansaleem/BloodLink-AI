import math
from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required, current_user
from app.extensions import db, get_client_ip
from app.utils.decorators import role_required
from app.models.donor import DonorProfile
from app.models.request import BloodRequest
from app.models.rewards import Coupon, CouponRedemption, RewardTransaction
from app.models.donation import Donation
from app.models.communication import DonorRequestResponse, DonorInvitation, Conversation
from app.models.audit import AuditLog
from app.notifications.services import create_notification
from app.matching.compatibility import (
    is_preliminarily_compatible,
    evaluate_component_compatibility,
    is_component_supported_for_automated_matching
)
from app.rewards.services import redeem_coupon

donor_bp = Blueprint('donor', __name__, url_prefix='/donor')


def calculate_distance_km(lat1, lon1, lat2, lon2):
    """Compute approximate haversine distance in kilometers between two geo points."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    try:
        R = 6371.0
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = math.sin(dlat / 2)**2 + math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(R * c, 1)
    except (ValueError, TypeError):
        return None


@donor_bp.before_request
@login_required
@role_required('DONOR')
def enforce_donor_role():
    pass


@donor_bp.route('/dashboard')
def dashboard():
    profile = current_user.donor_profile
    if not profile:
        flash("Please complete your donor profile.", "warning")
        return redirect(url_for('donor.profile'))

    is_eligible, cooldown_days = profile.is_eligible_to_donate()

    # Query active donor responses map for fast lookup
    my_responses = DonorRequestResponse.query.filter_by(donor_id=current_user.id)\
        .order_by(DonorRequestResponse.created_at.desc()).all()
    my_responses_by_req = {resp.blood_request_id: resp for resp in my_responses}

    # Query active hospital invitations for this donor
    my_invitations = DonorInvitation.query.filter_by(donor_id=current_user.id)\
        .order_by(DonorInvitation.created_at.desc()).all()

    # Find active verified requests that this donor can preliminarily help with
    # Privacy rule: Only display requests from verified hospitals; exclude cancelled, fulfilled, expired, flagged
    active_requests = BloodRequest.query.filter(
        BloodRequest.request_status.notin_(['FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'FLAGGED_FOR_REVIEW', 'VALIDATION_FAILED']),
        BloodRequest.verification_status == 'VERIFIED'
    ).order_by(BloodRequest.priority_score.desc()).limit(15).all()

    compatible_requests = []
    clinical_review_requests = []
    for req in active_requests:
        # Check that requesting hospital exists and is verified
        if not req.requesting_organization or not req.requesting_organization.is_verified:
            continue
        if not req.is_active:
            continue

        eval_res = evaluate_component_compatibility(
            profile.declared_blood_group,
            req.blood_group,
            req.component_type
        )

        req.approx_distance = calculate_distance_km(profile.latitude, profile.longitude, req.latitude, req.longitude)
        req.donor_response = my_responses_by_req.get(req.id)

        if eval_res['is_compatible']:
            req.match_category = 'COMPATIBLE'
            req.match_status_label = 'Compatible Match'
            req.match_reason = eval_res['reason']
            req.requires_clinical_review = False
            compatible_requests.append(req)
        elif eval_res['status'] == 'REQUIRES_CLINICAL_REVIEW':
            req.match_category = 'REQUIRES_CLINICAL_REVIEW'
            req.match_status_label = 'Requires Clinical Review'
            req.match_reason = eval_res['reason']
            req.requires_clinical_review = True
            clinical_review_requests.append(req)
        # Incompatible requests are never shown as eligible matches

    # Donation history
    donations = current_user.donations.order_by(Donation.donation_date.desc()).all()

    # Redemptions history
    redemptions = current_user.redemptions.order_by(CouponRedemption.created_at.desc()).all()

    # Available coupons preview
    available_coupons = Coupon.query.filter_by(coupon_status='ACTIVE').limit(4).all()

    # Profile completion check
    completion_fields = [profile.declared_blood_group, profile.city, profile.district, profile.phone]
    completion_pct = int((sum(1 for f in completion_fields if f) / len(completion_fields)) * 100)
    clinical_status = profile.get_clinical_status()

    return render_template(
        'donor/dashboard.html',
        profile=profile,
        clinical_status=clinical_status,
        is_eligible=is_eligible,
        cooldown_days=cooldown_days,
        compatible_requests=compatible_requests,
        clinical_review_requests=clinical_review_requests,
        opportunities=compatible_requests,
        my_responses=my_responses,
        my_invitations=my_invitations,
        donations=donations,
        redemptions=redemptions,
        available_coupons=available_coupons,
        completion_pct=completion_pct,
        balance=current_user.reward_balance
    )


@donor_bp.route('/respond/<int:request_id>', methods=['POST'])
@donor_bp.route('/request/<int:request_id>/respond', methods=['POST'])
def respond_to_request(request_id):
    """'I'm Ready to Donate' action handler: records willingness with validation and hospital notification."""
    profile = current_user.donor_profile
    if not profile:
        flash("Please complete your donor profile first.", "warning")
        return redirect(url_for('donor.dashboard'))

    req = BloodRequest.query.get_or_404(request_id)

    # Validation 1: Request must be active and belongs to a verified hospital
    if not req.is_active or req.verification_status != 'VERIFIED':
        flash("This blood request is no longer active for donor responses.", "warning")
        return redirect(request.referrer or url_for('donor.dashboard'))

    if not req.requesting_organization or not req.requesting_organization.is_verified:
        flash("Responses are permitted only for requests from verified healthcare facilities.", "warning")
        return redirect(request.referrer or url_for('donor.dashboard'))

    # Validation 2: Donor availability & consent check
    if not profile.availability_status:
        flash("Your standby status is currently set to paused. Please update your availability status to ready before responding to donation opportunities.", "warning")
        return redirect(request.referrer or url_for('donor.dashboard'))

    is_eligible, cooldown_days = profile.is_eligible_to_donate()
    if not is_eligible:
        flash(
            f"Cannot respond to request: You are currently restricted under clinical recovery rules "
            f"({cooldown_days} day(s) remaining until next eligible donation date).",
            "warning"
        )
        return redirect(request.referrer or url_for('donor.dashboard'))

    if not profile.notification_consent:
        flash("You have opted out of direct donation notifications. Please enable notifications in your profile settings.", "warning")
        return redirect(request.referrer or url_for('donor.dashboard'))

    # Validation 3: Component-aware compatibility and clinical review check
    eval_res = evaluate_component_compatibility(profile.declared_blood_group, req.blood_group, req.component_type)
    if eval_res['status'] == 'REQUIRES_CLINICAL_REVIEW':
        flash(f"Clinical Notice: Requests for '{req.component_type}' require individualized laboratory evaluation by the attending hospital pathologist before donor engagement.", "warning")
        return redirect(request.referrer or url_for('donor.dashboard'))

    if not eval_res['is_compatible']:
        flash(f"Preliminary check: Your blood group ({profile.declared_blood_group}) is not compatible with request ({req.blood_group} {req.component_type}).", "warning")
        return redirect(request.referrer or url_for('donor.dashboard'))

    # Validation 4: Duplicate active response prevention (database & application level)
    existing_resp = DonorRequestResponse.query.filter_by(
        donor_id=current_user.id,
        blood_request_id=req.id
    ).first()

    custom_message = request.form.get('response_message', '').strip()

    try:
        if existing_resp:
            if existing_resp.response_status == 'WITHDRAWN':
                # Reactivate withdrawn response
                existing_resp.response_status = 'INTERESTED'
                existing_resp.response_message = custom_message or existing_resp.response_message
                existing_resp.withdrawn_at = None
                existing_resp.updated_at = datetime.now(timezone.utc)
            else:
                flash(f"You have already responded to blood request {req.request_reference} with status: {existing_resp.response_status}.", "info")
                return redirect(request.referrer or url_for('donor.dashboard'))
        else:
            new_resp = DonorRequestResponse(
                donor_id=current_user.id,
                blood_request_id=req.id,
                response_status='INTERESTED',
                response_message=custom_message,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.session.add(new_resp)

        # Synchronize direct invitation if present
        inv = DonorInvitation.query.filter_by(
            donor_id=current_user.id,
            blood_request_id=req.id
        ).first()
        if inv and inv.invitation_status == 'SENT':
            inv.invitation_status = 'ACCEPTED'
            inv.responded_at = datetime.now(timezone.utc)

        if req.request_status in ('ACTIVE_MATCHING', 'MATCHING', 'SUBMITTED', 'VERIFIED'):
            req.request_status = 'DONOR_RESPONDED'
            req.updated_at = datetime.now(timezone.utc)

        # Notify hospital authorized staff members
        for membership in req.requesting_organization.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='DONOR_RESPONSE_RECEIVED',
                title='Donor Ready to Donate!',
                message=f"Voluntary Donor {current_user.name} ({profile.declared_blood_group}) responded 'I am Ready to Donate' for request {req.request_reference}."
            )

        # Record event in protected audit log
        AuditLog.log(
            action='DONOR_RESPONSE',
            entity_type='BloodRequest',
            entity_id=req.id,
            details=f"Donor {current_user.email} expressed interest to donate for request {req.request_reference}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )

        db.session.commit()

        flash(
            f"Thank you, {current_user.name}! Your willingness to donate for request {req.request_reference} "
            f"has been transmitted to {req.requesting_organization.organization_name}. "
            "Please note: Expressing willingness to respond does not confirm medical eligibility or transfusion compatibility. "
            "Qualified medical personnel will verify physiological suitability upon clinical arrival.",
            "success"
        )
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Donor Response Error]: {e}")
        flash("A database error occurred while registering your response. Please try again.", "danger")

    return redirect(request.referrer or url_for('donor.dashboard'))


@donor_bp.route('/response/<int:response_id>/withdraw', methods=['POST'])
def withdraw_response(response_id):
    """Allows voluntary donors to gracefully withdraw an unfulfilled donation response."""
    resp = DonorRequestResponse.query.get_or_404(response_id)

    # Authorization Check: only the owning donor can withdraw their response
    if resp.donor_id != current_user.id:
        abort(403)

    success, msg = resp.withdraw()
    if not success:
        flash(msg, "warning")
        return redirect(url_for('donor.dashboard'))

    try:
        # Notify hospital clinical staff
        for membership in resp.blood_request.requesting_organization.memberships:
            create_notification(
                recipient_id=membership.user_id,
                notification_type='DONOR_RESPONSE_WITHDRAWN',
                title='Donor Response Withdrawn',
                message=f"Donor {current_user.name} withdrew their response for blood request {resp.blood_request.request_reference}."
            )

        AuditLog.log(
            action='WITHDRAW_RESPONSE',
            entity_type='DonorRequestResponse',
            entity_id=resp.id,
            details=f"Donor {current_user.email} withdrew response for request {resp.blood_request.request_reference}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()
        flash("Your donation response has been withdrawn. Hospital coordinators have been informed.", "info")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Withdraw Response Error]: {e}")
        flash("Could not withdraw response at this time.", "danger")

    return redirect(url_for('donor.dashboard'))


@donor_bp.route('/invitation/<int:invitation_id>/respond', methods=['POST'])
def respond_to_invitation(invitation_id):
    """Handle voluntary donor response to a hospital direct donation invitation."""
    inv = DonorInvitation.query.get_or_404(invitation_id)

    if inv.donor_id != current_user.id:
        abort(403)

    raw_decision = (request.form.get('decision') or request.form.get('action') or '').strip().upper()
    if raw_decision in ('ACCEPT', 'READY', 'I AM READY', "I'M READY TO DONATE"):
        decision = 'ACCEPT'
    elif raw_decision in ('DECLINE', 'DECLINE REQUEST'):
        decision = 'DECLINE'
    else:
        decision = raw_decision

    profile = current_user.donor_profile

    if decision not in ('ACCEPT', 'DECLINE'):
        flash("Invalid invitation decision specified.", "warning")
        return redirect(request.referrer or url_for('donor.dashboard'))

    try:
        if decision == 'ACCEPT':
            # Validation 0: Prevent duplicate acceptance
            if inv.invitation_status == 'ACCEPTED':
                flash("You have already confirmed your willingness to donate for this invitation.", "info")
                return redirect(request.referrer or url_for('donor.dashboard'))

            # Validation 1: Donor profile verification
            if not profile or profile.verification_status not in ('APPROVED', 'VERIFIED'):
                flash("Your donor profile is pending verification. Only verified donors may accept invitations.", "warning")
                return redirect(request.referrer or url_for('donor.dashboard'))

            # Validation 2: Donor availability & recovery cooldown
            if not profile.availability_status:
                flash("You are currently marked as unavailable. Please toggle your standby status to ready before accepting invitations.", "warning")
                return redirect(request.referrer or url_for('donor.dashboard'))

            is_eligible, days_left = profile.is_eligible_to_donate()
            if not is_eligible:
                flash(
                    f"Cannot accept invitation: You are currently restricted under clinical recovery rules "
                    f"({days_left} day(s) remaining until next eligible donation date).",
                    "danger"
                )
                return redirect(request.referrer or url_for('donor.dashboard'))

            if not profile.notification_consent:
                flash("Cannot accept invitation: You have opted out of direct donation notifications. Please enable notifications in your profile settings.", "warning")
                return redirect(request.referrer or url_for('donor.dashboard'))

            # Validation 3: Request status and facility authorization
            req = inv.blood_request
            if not req or not req.is_active or req.verification_status != 'VERIFIED':
                flash("Cannot accept invitation: This blood request is no longer active.", "warning")
                return redirect(request.referrer or url_for('donor.dashboard'))

            if not inv.hospital or not inv.hospital.is_verified:
                flash("Cannot accept invitation from an unverified healthcare facility.", "warning")
                return redirect(request.referrer or url_for('donor.dashboard'))

            # Validation 4: Component and blood group compatibility
            eval_res = evaluate_component_compatibility(
                profile.declared_blood_group,
                req.blood_group,
                req.component_type
            )
            if not eval_res['is_compatible']:
                flash(
                    f"Backend verification rejected: Your blood group ({profile.declared_blood_group}) is not compatible with request "
                    f"({req.blood_group} {req.component_type}).",
                    "danger"
                )
                return redirect(request.referrer or url_for('donor.dashboard'))

            inv.invitation_status = 'ACCEPTED'
            inv.responded_at = datetime.now(timezone.utc)

            # Ensure corresponding response record exists in CONFIRMED status
            existing_resp = DonorRequestResponse.query.filter_by(
                donor_id=current_user.id,
                blood_request_id=inv.blood_request_id
            ).first()
            if existing_resp:
                existing_resp.response_status = 'CONFIRMED'
                existing_resp.withdrawn_at = None
                existing_resp.updated_at = datetime.now(timezone.utc)
            else:
                new_resp = DonorRequestResponse(
                    donor_id=current_user.id,
                    blood_request_id=inv.blood_request_id,
                    response_status='CONFIRMED',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.session.add(new_resp)

            if inv.blood_request.request_status in ('ACTIVE_MATCHING', 'MATCHING', 'SUBMITTED', 'VERIFIED'):
                inv.blood_request.request_status = 'DONOR_RESPONDED'
                inv.blood_request.updated_at = datetime.now(timezone.utc)

            for membership in inv.hospital.memberships:
                create_notification(
                    recipient_id=membership.user_id,
                    notification_type='INVITATION_ACCEPTED',
                    title='Donation Invitation Accepted',
                    message=f"Donor {current_user.name} accepted your donation invitation for blood request {inv.blood_request.request_reference}."
                )

            AuditLog.log(
                action='ACCEPT_INVITATION',
                entity_type='DonorInvitation',
                entity_id=inv.id,
                details=f"Donor {current_user.email} accepted invitation from {inv.hospital.organization_name}",
                actor_id=current_user.id,
                ip_address=get_client_ip()
            )
            flash(
                f"You have accepted the donation invitation from {inv.hospital.organization_name}! Thank you for stepping forward. "
                "Please note: Accepting an invitation indicates your willingness to donate. It does not constitute final medical clearance "
                "or clinical cross-match confirmation, which must be verified upon arrival.",
                "success"
            )

        elif decision == 'DECLINE':
            inv.invitation_status = 'DECLINED'
            inv.responded_at = datetime.now(timezone.utc)

            existing_resp = DonorRequestResponse.query.filter_by(
                donor_id=current_user.id,
                blood_request_id=inv.blood_request_id
            ).first()
            if existing_resp:
                existing_resp.response_status = 'DECLINED'
                existing_resp.updated_at = datetime.now(timezone.utc)

            for membership in inv.hospital.memberships:
                create_notification(
                    recipient_id=membership.user_id,
                    notification_type='INVITATION_DECLINED',
                    title='Donation Invitation Declined',
                    message=f"Donor {current_user.name} declined the donation invitation for blood request {inv.blood_request.request_reference}."
                )

            AuditLog.log(
                action='DECLINE_INVITATION',
                entity_type='DonorInvitation',
                entity_id=inv.id,
                details=f"Donor {current_user.email} declined invitation for request {inv.blood_request.request_reference}",
                actor_id=current_user.id,
                ip_address=get_client_ip()
            )
            flash("You have declined the donation invitation. The hospital coordinators have been informed.", "info")

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Invitation Respond Error]: {e}")
        flash("Could not record invitation response.", "danger")

    return redirect(request.referrer or url_for('donor.dashboard'))


@donor_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    profile = current_user.donor_profile
    if not profile:
        profile = DonorProfile(
            user_id=current_user.id,
            declared_blood_group='O+',
            country='India',
            availability_status=True,
            notification_consent=True
        )
        try:
            db.session.add(profile)
            db.session.commit()
        except Exception:
            db.session.rollback()

    if request.method == 'POST':
        new_state = request.form.get('state', profile.state or '').strip()
        new_district = request.form.get('district', profile.district or '').strip()

        from app.locations import is_valid_state, is_valid_district
        if new_state and not is_valid_state(new_state):
            flash(f"Invalid State: '{new_state}'. Please select a valid Indian State or UT.", "warning")
            return render_template('donor/profile.html', profile=profile)
        if new_state and new_district and not is_valid_district(new_state, new_district):
            flash(f"Invalid District: '{new_district}' does not belong to {new_state}.", "warning")
            return render_template('donor/profile.html', profile=profile)

        try:
            profile.state = new_state
            profile.district = new_district
            profile.city = request.form.get('city', profile.city or '').strip()
            profile.phone = request.form.get('phone', profile.phone or '').strip()
            profile.availability_status = bool(request.form.get('availability_status'))
            profile.notification_consent = bool(request.form.get('notification_consent'))

            try:
                profile.latitude = float(request.form.get('latitude', profile.latitude or 12.9716))
                profile.longitude = float(request.form.get('longitude', profile.longitude or 77.5946))
            except (ValueError, TypeError):
                pass

            db.session.commit()
            flash("Your profile and privacy settings have been updated.", "success")
            return redirect(url_for('donor.dashboard'))
        except Exception as e:
            db.session.rollback()
            flash("An error occurred while saving your profile changes.", "danger")
            return render_template('donor/profile.html', profile=profile)

    return render_template('donor/profile.html', profile=profile)


@donor_bp.route('/availability/toggle', methods=['POST'])
def toggle_availability():
    profile = current_user.donor_profile
    if profile:
        try:
            profile.availability_status = not profile.availability_status
            db.session.commit()
            status_text = "Available" if profile.availability_status else "Unavailable"
            flash(f"Your status has been updated to: {status_text}.", "info")
        except Exception:
            db.session.rollback()
            flash("Could not update availability at this time.", "danger")
    return redirect(url_for('donor.dashboard'))


@donor_bp.route('/rewards')
def rewards():
    coupons = Coupon.query.filter_by(coupon_status='ACTIVE').all()
    redemptions = current_user.redemptions.order_by(CouponRedemption.created_at.desc()).all()
    transactions = current_user.reward_transactions.order_by(RewardTransaction.created_at.desc()).all()
    
    return render_template(
        'donor/rewards.html',
        coupons=coupons,
        redemptions=redemptions,
        transactions=transactions,
        balance=current_user.reward_balance
    )


@donor_bp.route('/redeem/<int:coupon_id>', methods=['POST'])
def redeem(coupon_id):
    success, message, code = redeem_coupon(current_user.id, coupon_id)
    if success:
        flash(f"{message} Your Voucher Code: {code}", "success")
    else:
        flash(message, "danger")
    return redirect(url_for('donor.rewards'))
