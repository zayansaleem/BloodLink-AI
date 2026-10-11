from datetime import datetime, timezone, date
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.utils.decorators import role_required, verified_org_required
from app.models.inventory import BloodInventory
from app.models.donation import Donation
from app.models.user import User
from app.models.request import BloodRequest
from app.models.communication import BloodBankResponse
from app.models.audit import AuditLog
from app.rewards.services import award_donation_points
from app.notifications.services import create_notification
from app.matching.engine import haversine_distance
from app.matching.compatibility import evaluate_component_compatibility

blood_bank_bp = Blueprint('blood_bank', __name__, url_prefix='/blood-bank')


@blood_bank_bp.before_request
@login_required
@role_required('BLOOD_BANK')
def enforce_blood_bank_role():
    pass


@blood_bank_bp.route('/dashboard')
def dashboard():
    org = current_user.organization
    if not org:
        flash("No blood bank organization affiliated with your account.", "danger")
        return redirect(url_for('main.index'))

    inventories = BloodInventory.query.filter_by(blood_bank_id=org.id).all()
    pending_donations = Donation.query.filter_by(blood_bank_id=org.id, verification_status='PENDING').count()
    outdated_count = sum(1 for inv in inventories if inv.is_outdated)

    # Component summary
    component_summary = {}
    for comp in ['Whole Blood', 'Red Blood Cells', 'Platelets', 'Plasma']:
        total = sum(inv.available_units for inv in inventories if inv.component_type == comp)
        component_summary[comp] = total

    # Query active emergency requests for coordination
    open_requests = BloodRequest.query.filter(
        BloodRequest.verification_status == 'VERIFIED',
        BloodRequest.request_status.notin_(['FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'FLAGGED_FOR_REVIEW', 'VALIDATION_FAILED'])
    ).order_by(BloodRequest.priority_score.desc()).limit(12).all()

    my_inventories = {
        (inv.blood_group, inv.component_type): inv
        for inv in inventories
    }
    my_responses = {
        resp.blood_request_id: resp
        for resp in BloodBankResponse.query.filter_by(blood_bank_id=org.id).all()
    }

    emergency_requests_data = []
    for req in open_requests:
        inv = my_inventories.get((req.blood_group, req.component_type))
        available = inv.available_units if inv else 0
        reserved = getattr(inv, 'reserved_units', 0) if inv else 0
        unreserved = max(0, available - reserved)

        dist = None
        if org.latitude is not None and org.longitude is not None and req.latitude is not None and req.longitude is not None:
            dist = haversine_distance(org.latitude, org.longitude, req.latitude, req.longitude)

        resp = my_responses.get(req.id)
        emergency_requests_data.append({
            'request': req,
            'my_available_units': available,
            'my_reserved_units': reserved,
            'my_unreserved_units': unreserved,
            'my_response': resp,
            'distance_km': dist,
            'has_sufficient_stock': unreserved >= req.units_required
        })

    return render_template(
        'blood_bank/dashboard.html',
        org=org,
        inventories=inventories,
        pending_donations=pending_donations,
        outdated_count=outdated_count,
        component_summary=component_summary,
        total_units=org.total_reported_units,
        emergency_requests=emergency_requests_data
    )


@blood_bank_bp.route('/inventory')
def inventory():
    org = current_user.organization
    group_filter = request.args.get('blood_group', '').strip().upper()
    comp_filter = request.args.get('component_type', '').strip()

    query = BloodInventory.query.filter_by(blood_bank_id=org.id)
    if group_filter:
        query = query.filter_by(blood_group=group_filter)
    if comp_filter:
        query = query.filter_by(component_type=comp_filter)

    inventories = query.order_by(BloodInventory.blood_group, BloodInventory.component_type).all()
    history = AuditLog.query.filter_by(action='UPDATE_INVENTORY')\
        .order_by(AuditLog.created_at.desc()).limit(10).all()

    return render_template(
        'blood_bank/inventory.html',
        org=org,
        inventories=inventories,
        selected_group=group_filter,
        selected_comp=comp_filter,
        history=history
    )


@blood_bank_bp.route('/inventory/update', methods=['GET', 'POST'])
@verified_org_required
def update_inventory():
    org = current_user.organization

    if request.method == 'POST':
        blood_group = request.form.get('blood_group', '').strip().upper()
        component_type = request.form.get('component_type', 'Whole Blood').strip()
        units_val = request.form.get('available_units', '').strip()

        try:
            available_units = int(units_val)
            if available_units < 0:
                raise ValueError("Units cannot be negative.")
        except (ValueError, TypeError):
            flash("Invalid quantity: Blood unit counts cannot be negative.", "danger")
            return redirect(url_for('blood_bank.inventory'))

        # Find existing or create new
        record = BloodInventory.query.filter_by(
            blood_bank_id=org.id,
            blood_group=blood_group,
            component_type=component_type
        ).first()

        if record:
            prev_units = record.available_units
            record.available_units = available_units
            record.last_updated_at = datetime.now(timezone.utc)
            record.updated_by = current_user.id
            action_desc = f"Updated {blood_group} ({component_type}) from {prev_units} to {available_units} units"
        else:
            record = BloodInventory(
                blood_bank_id=org.id,
                blood_group=blood_group,
                component_type=component_type,
                available_units=available_units,
                last_updated_at=datetime.now(timezone.utc),
                updated_by=current_user.id
            )
            db.session.add(record)
            action_desc = f"Initialized {blood_group} ({component_type}) with {available_units} units"

        try:
            AuditLog.log(
                action='UPDATE_INVENTORY',
                entity_type='BloodInventory',
                entity_id=record.id if record.id else None,
                details=action_desc,
                actor_id=current_user.id
            )
            db.session.commit()
            flash(f"Inventory saved: {blood_group} {component_type} set to {available_units} units.", "success")
        except Exception as e:
            db.session.rollback()
            import logging
            logging.getLogger(__name__).error(f"[Inventory Error] Failed to update inventory: {e}")
            flash("Database error occurred while updating inventory. Please try again.", "danger")
        return redirect(url_for('blood_bank.inventory'))

    return redirect(url_for('blood_bank.inventory'))


@blood_bank_bp.route('/donations')
def donations():
    org = current_user.organization
    pending = Donation.query.filter_by(blood_bank_id=org.id, verification_status='PENDING')\
        .order_by(Donation.donation_date.desc()).all()
    verified = Donation.query.filter_by(blood_bank_id=org.id, verification_status='VERIFIED')\
        .order_by(Donation.verified_at.desc()).limit(20).all()

    return render_template(
        'blood_bank/verify_donations.html',
        org=org,
        pending_donations=pending,
        verified_donations=verified
    )


@blood_bank_bp.route('/donations/record-new', methods=['POST'])
@verified_org_required
def record_donation():
    """Record an in-person voluntary donation at this blood bank facility."""
    org = current_user.organization
    donor_email = request.form.get('donor_email', '').strip().lower()
    component_type = request.form.get('component_type', 'Whole Blood').strip()
    units = int(request.form.get('units', 1))
    notes = request.form.get('notes', '').strip()

    donor = User.query.filter_by(email=donor_email, role='DONOR').first()
    if not donor:
        flash("Donor email not found. Please verify the donor has registered an account.", "danger")
        return redirect(url_for('blood_bank.donations'))

    try:
        new_donation = Donation(
            donor_id=donor.id,
            blood_bank_id=org.id,
            component_type=component_type,
            units=units,
            donation_date=datetime.now(timezone.utc),
            verification_status='PENDING',
            notes=notes
        )
        db.session.add(new_donation)
        db.session.commit()
        flash(f"Donation intake recorded for donor {donor.name}. Queued for clinical verification.", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Donation Intake Error]: {e}")
        flash("Database error occurred while recording donation intake.", "danger")

    return redirect(url_for('blood_bank.donations'))


@blood_bank_bp.route('/donations/<int:donation_id>/verify', methods=['POST'])
@verified_org_required
def verify_donation(donation_id):
    org = current_user.organization
    donation = Donation.query.get_or_404(donation_id)

    if donation.blood_bank_id != org.id:
        abort(403)

    if donation.donor_id == current_user.id:
        flash("Unauthorized: Clinical staff cannot verify their own personal blood donation.", "danger")
        return redirect(url_for('blood_bank.donations'))

    if donation.verification_status == 'VERIFIED':
        flash("This donation record has already been verified.", "info")
        return redirect(url_for('blood_bank.donations'))

    try:
        # Mark as verified
        donation.verification_status = 'VERIFIED'
        donation.verified_by = current_user.id
        donation.verified_at = datetime.now(timezone.utc)

        # Update donor recovery policy in profile
        donor = db.session.get(User, donation.donor_id)
        if donor and donor.donor_profile:
            from datetime import timedelta
            don_dt = donation.donation_date.date() if isinstance(donation.donation_date, datetime) else (donation.donation_date or date.today())
            donor.donor_profile.last_donation_date = don_dt

            # Approved clinical recovery intervals
            cooldown_days = 56
            if donation.component_type == 'Red Blood Cells':
                cooldown_days = 112
            elif donation.component_type == 'Platelets':
                cooldown_days = 14
            elif donation.component_type == 'Plasma':
                cooldown_days = 28

            donor.donor_profile.recovery_period_days = cooldown_days
            donor.donor_profile.next_eligible_date = don_dt + timedelta(days=cooldown_days)
            donor.donor_profile.clinical_review_required = False

        AuditLog.log(
            action='VERIFY_DONATION',
            entity_type='Donation',
            entity_id=donation.id,
            details=f"Verified donation #{donation.id} for Donor {donation.donor_id}",
            actor_id=current_user.id
        )

        db.session.commit()

        # Automatically credit reward points (100 demonstration points per verified unit)
        points_to_award = 100 * donation.units
        award_donation_points(donation.id, points=points_to_award)

        flash(f"Donation #{donation.id} verified. {points_to_award} Lifesaver points credited to {donor.name}!", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Donation Verify Error]: {e}")
        flash("Database error occurred while verifying donation.", "danger")

    return redirect(url_for('blood_bank.donations'))


@blood_bank_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    org = current_user.organization
    if not org:
        flash("No blood bank affiliated with your account.", "danger")
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        new_phone = request.form.get('contact_phone', org.contact_phone).strip()
        new_email = request.form.get('contact_email', org.contact_email).strip().lower()
        new_address = request.form.get('address', org.address).strip()
        new_state = request.form.get('state', org.state).strip()
        new_district = request.form.get('district', org.district).strip()
        new_city = request.form.get('city', org.city).strip()

        from app.locations import is_valid_state, is_valid_district
        if new_state and not is_valid_state(new_state):
            flash(f"Invalid State: '{new_state}'.", "warning")
            return render_template('blood_bank/profile.html', org=org)
        if new_state and new_district and not is_valid_district(new_state, new_district):
            flash(f"Invalid District: '{new_district}'.", "warning")
            return render_template('blood_bank/profile.html', org=org)

        try:
            org.contact_phone = new_phone
            org.contact_email = new_email
            org.address = new_address
            org.state = new_state
            org.district = new_district
            org.city = new_city
            org.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            flash("Blood bank profile and contact details updated successfully.", "success")
            return redirect(url_for('blood_bank.dashboard'))
        except Exception:
            db.session.rollback()
            flash("An error occurred while updating blood bank profile.", "danger")

    return render_template('blood_bank/profile.html', org=org)


@blood_bank_bp.route('/requests')
def requests():
    """Display active hospital blood requests suitable for coordination with this blood bank."""
    org = current_user.organization
    if not org:
        flash("No blood bank affiliated with your account.", "danger")
        return redirect(url_for('main.index'))

    # Query active hospital requests
    query = BloodRequest.query.filter(
        BloodRequest.verification_status == 'VERIFIED',
        BloodRequest.request_status.notin_(['FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'FLAGGED_FOR_REVIEW', 'VALIDATION_FAILED'])
    )

    group_filter = request.args.get('blood_group', '').strip().upper()
    comp_filter = request.args.get('component_type', '').strip()

    if group_filter:
        query = query.filter_by(blood_group=group_filter)
    if comp_filter:
        query = query.filter_by(component_type=comp_filter)

    open_requests = query.order_by(BloodRequest.priority_score.desc()).all()

    # Pre-fetch this blood bank's inventory and responses map
    my_inventories = {
        (inv.blood_group, inv.component_type): inv
        for inv in BloodInventory.query.filter_by(blood_bank_id=org.id).all()
    }
    my_responses = {
        resp.blood_request_id: resp
        for resp in BloodBankResponse.query.filter_by(blood_bank_id=org.id).all()
    }

    req_data = []
    for req in open_requests:
        inv = my_inventories.get((req.blood_group, req.component_type))
        available = inv.available_units if inv else 0
        reserved = inv.reserved_units if inv else 0

        # Calculate approximate distance
        dist = None
        if org.latitude is not None and org.longitude is not None and req.latitude is not None and req.longitude is not None:
            dist = haversine_distance(org.latitude, org.longitude, req.latitude, req.longitude)

        resp = my_responses.get(req.id)
        clinical_eval = evaluate_component_compatibility(req.blood_group, req.blood_group, req.component_type)

        req_data.append({
            'request': req,
            'my_available_units': available,
            'my_reserved_units': reserved,
            'my_response': resp,
            'distance_km': dist,
            'requires_clinical_review': (clinical_eval['status'] == 'REQUIRES_CLINICAL_REVIEW')
        })

    return render_template(
        'blood_bank/requests.html',
        org=org,
        requests_data=req_data,
        selected_group=group_filter,
        selected_comp=comp_filter
    )


@blood_bank_bp.route('/request/<int:request_id>/respond', methods=['POST'])
@verified_org_required
def respond_to_request(request_id):
    """Transaction-safe response and inventory reservation handler for hospital requests."""
    org = current_user.organization
    if not org or not org.is_verified or org.verification_status == 'SUSPENDED':
        flash("Unauthorized: Facility is unverified or suspended.", "danger")
        return redirect(url_for('blood_bank.requests'))

    req = BloodRequest.query.get_or_404(request_id)
    if not req.is_active or req.verification_status != 'VERIFIED':
        flash("This blood request is no longer active for coordination.", "warning")
        return redirect(url_for('blood_bank.requests'))

    raw_decision = (request.form.get('decision') or request.form.get('action') or '').strip().upper()
    if raw_decision in ('ACCEPT', 'WE_HAVE_BLOOD_AVAILABLE', 'AVAILABLE', 'WE HAVE BLOOD AVAILABLE'):
        decision = 'ACCEPT'
    elif raw_decision in ('CHECK_AVAILABILITY', 'REVIEWING', 'CHECK', 'CHECK AVAILABILITY'):
        decision = 'CHECK_AVAILABILITY'
    elif raw_decision in ('DECLINE', 'UNABLE_TO_FULFIL', 'UNABLE TO FULFIL'):
        decision = 'DECLINE'
    else:
        decision = raw_decision

    notes = request.form.get('notes', '').strip()

    valid_decisions = {'ACCEPT', 'CHECK_AVAILABILITY', 'DECLINE', 'INSUFFICIENT_INVENTORY', 'ADDITIONAL_VERIFICATION_REQUIRED'}
    if decision not in valid_decisions:
        flash("Invalid coordination action selected.", "warning")
        return redirect(request.referrer or url_for('blood_bank.requests'))

    existing_resp = BloodBankResponse.query.filter_by(
        blood_bank_id=org.id,
        blood_request_id=req.id
    ).first()

    # Find the corresponding inventory record
    inv = BloodInventory.query.filter_by(
        blood_bank_id=org.id,
        blood_group=req.blood_group,
        component_type=req.component_type
    ).first()

    try:
        if decision == 'ACCEPT':
            units_raw = (request.form.get('units_to_reserve') or request.form.get('units_allocated') or '1').strip()
            try:
                units_to_reserve = int(units_raw)
            except ValueError:
                units_to_reserve = 1

            if units_to_reserve <= 0 or units_to_reserve > req.units_required:
                flash(f"Units to reserve must be between 1 and requested quantity ({req.units_required}).", "warning")
                return redirect(request.referrer or url_for('blood_bank.requests'))

            if not inv or inv.available_units < units_to_reserve:
                avail = inv.available_units if inv else 0
                flash(f"Insufficient stock: Available units ({avail}) are less than required reservation ({units_to_reserve}).", "danger")
                return redirect(request.referrer or url_for('blood_bank.requests'))

            # If there was a previous reservation from this bank, release it first before re-reserving
            if existing_resp and existing_resp.units_reserved > 0:
                inv.release_reserved_units(existing_resp.units_reserved)

            # Transaction-safe reservation
            if not inv.reserve_units(units_to_reserve):
                flash("Could not complete stock reservation. Inventory units unavailable.", "danger")
                return redirect(request.referrer or url_for('blood_bank.requests'))

            if existing_resp:
                existing_resp.response_status = 'ACCEPTED'
                existing_resp.units_reserved = units_to_reserve
                existing_resp.response_notes = notes or existing_resp.response_notes
                existing_resp.updated_at = datetime.now(timezone.utc)
            else:
                new_resp = BloodBankResponse(
                    blood_bank_id=org.id,
                    blood_request_id=req.id,
                    responder_user_id=current_user.id,
                    response_status='ACCEPTED',
                    units_reserved=units_to_reserve,
                    response_notes=notes or None,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.session.add(new_resp)

            # Update request status to reflect blood bank coordination
            if req.request_status in ('ACTIVE_MATCHING', 'MATCHING', 'SUBMITTED', 'VERIFIED'):
                req.request_status = 'BLOOD_BANK_RESPONDED'
                req.updated_at = datetime.now(timezone.utc)

            # Notify requesting hospital staff
            for membership in req.requesting_organization.memberships:
                create_notification(
                    recipient_id=membership.user_id,
                    notification_type='BLOOD_BANK_ACCEPTED',
                    title='Blood Bank Coordination Accepted!',
                    message=f"{org.organization_name} accepted request {req.request_reference} and reserved {units_to_reserve} unit(s) of {req.blood_group} {req.component_type}."
                )

            AuditLog.log(
                action='BLOOD_BANK_ACCEPT_REQUEST',
                entity_type='BloodBankResponse',
                entity_id=req.id,
                details=f"Bank {org.organization_name} accepted request {req.request_reference} and reserved {units_to_reserve} units",
                actor_id=current_user.id
            )

            db.session.commit()
            flash(f"Coordination accepted! {units_to_reserve} unit(s) reserved for request {req.request_reference}. Hospital notified.", "success")

        elif decision == 'CHECK_AVAILABILITY':
            # Record facility review without pre-allocating inventory
            if existing_resp:
                existing_resp.response_status = 'REVIEWING'
                existing_resp.response_notes = notes or "Facility staff is actively checking physical stock availability"
                existing_resp.updated_at = datetime.now(timezone.utc)
            else:
                new_resp = BloodBankResponse(
                    blood_bank_id=org.id,
                    blood_request_id=req.id,
                    responder_user_id=current_user.id,
                    response_status='REVIEWING',
                    units_reserved=0,
                    response_notes=notes or "Facility staff is actively checking physical stock availability",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.session.add(new_resp)

            for membership in req.requesting_organization.memberships:
                create_notification(
                    recipient_id=membership.user_id,
                    notification_type='BLOOD_BANK_REVIEWING',
                    title='Blood Bank Reviewing Request',
                    message=f"{org.organization_name} is checking physical stock availability for request {req.request_reference}."
                )

            AuditLog.log(
                action='BLOOD_BANK_CHECK_AVAILABILITY',
                entity_type='BloodBankResponse',
                entity_id=req.id,
                details=f"Bank {org.organization_name} is checking availability for {req.request_reference}",
                actor_id=current_user.id
            )

            db.session.commit()
            flash(f"Availability check recorded for request {req.request_reference}. Inventory is not reserved until stock availability is confirmed.", "info")

        elif decision == 'DECLINE':
            decline_reason = notes or "Unable to fulfil requirement due to inventory or clinical constraints"

            # If there was a previous reservation, release it
            if existing_resp and existing_resp.units_reserved > 0 and inv:
                inv.release_reserved_units(existing_resp.units_reserved)

            if existing_resp:
                existing_resp.response_status = 'DECLINED'
                existing_resp.units_reserved = 0
                existing_resp.response_notes = decline_reason
                existing_resp.updated_at = datetime.now(timezone.utc)
            else:
                new_resp = BloodBankResponse(
                    blood_bank_id=org.id,
                    blood_request_id=req.id,
                    responder_user_id=current_user.id,
                    response_status='DECLINED',
                    units_reserved=0,
                    response_notes=decline_reason,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.session.add(new_resp)

            for membership in req.requesting_organization.memberships:
                create_notification(
                    recipient_id=membership.user_id,
                    notification_type='BLOOD_BANK_DECLINED',
                    title='Blood Bank Unable to Fulfil',
                    message=f"{org.organization_name} reported unable to fulfil request {req.request_reference}: {decline_reason}."
                )

            AuditLog.log(
                action='BLOOD_BANK_DECLINE_REQUEST',
                entity_type='BloodBankResponse',
                entity_id=req.id,
                details=f"Bank {org.organization_name} reported unable to fulfil {req.request_reference}. Reason: {decline_reason}",
                actor_id=current_user.id
            )

            db.session.commit()
            flash(f"Reported unable to fulfil request {req.request_reference}. Hospital coordinators have been informed.", "info")

        elif decision == 'INSUFFICIENT_INVENTORY':
            if existing_resp and existing_resp.units_reserved > 0 and inv:
                inv.release_reserved_units(existing_resp.units_reserved)

            if existing_resp:
                existing_resp.response_status = 'INSUFFICIENT_INVENTORY'
                existing_resp.units_reserved = 0
                existing_resp.response_notes = notes or "Insufficient reported stock"
                existing_resp.updated_at = datetime.now(timezone.utc)
            else:
                new_resp = BloodBankResponse(
                    blood_bank_id=org.id,
                    blood_request_id=req.id,
                    responder_user_id=current_user.id,
                    response_status='INSUFFICIENT_INVENTORY',
                    units_reserved=0,
                    response_notes=notes or "Insufficient reported stock",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.session.add(new_resp)

            AuditLog.log(
                action='BLOOD_BANK_REPORT_INSUFFICIENT',
                entity_type='BloodBankResponse',
                entity_id=req.id,
                details=f"Bank {org.organization_name} reported insufficient stock for {req.request_reference}",
                actor_id=current_user.id
            )

            db.session.commit()
            flash(f"Reported insufficient inventory for request {req.request_reference}.", "info")

        elif decision == 'ADDITIONAL_VERIFICATION_REQUIRED':
            if existing_resp:
                existing_resp.response_status = 'ADDITIONAL_VERIFICATION_REQUIRED'
                existing_resp.response_notes = notes or "Laboratory cross-match verification required"
                existing_resp.updated_at = datetime.now(timezone.utc)
            else:
                new_resp = BloodBankResponse(
                    blood_bank_id=org.id,
                    blood_request_id=req.id,
                    responder_user_id=current_user.id,
                    response_status='ADDITIONAL_VERIFICATION_REQUIRED',
                    units_reserved=0,
                    response_notes=notes or "Laboratory cross-match verification required",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.session.add(new_resp)

            # Notify hospital that clinical verification is required
            for membership in req.requesting_organization.memberships:
                create_notification(
                    recipient_id=membership.user_id,
                    notification_type='VERIFICATION_REQUIRED',
                    title='Clinical Verification Required',
                    message=f"{org.organization_name} requested additional clinical verification for request {req.request_reference}: {notes or 'Laboratory cross-match sample required'}."
                )

            AuditLog.log(
                action='BLOOD_BANK_VERIFICATION_REQUIRED',
                entity_type='BloodBankResponse',
                entity_id=req.id,
                details=f"Bank {org.organization_name} reported additional verification required for {req.request_reference}",
                actor_id=current_user.id
            )

            db.session.commit()
            flash(f"Clinical verification requirement registered for request {req.request_reference}.", "warning")

    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Blood Bank Response Error]: {e}")
        flash("A database error occurred while registering your response.", "danger")

    return redirect(url_for('blood_bank.requests'))

