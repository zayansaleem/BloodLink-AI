from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db, get_client_ip
from app.utils.decorators import role_required, verified_org_required
from app.models.request import BloodRequest, DonorMatch
from app.models.organization import Organization
from app.models.inventory import BloodInventory
from app.models.communication import DonorRequestResponse, DonorInvitation, Conversation, BloodBankResponse
from app.models.donor import DonorProfile
from app.models.audit import AuditLog
from app.models.user import User
from app.matching.prioritization import update_request_priority
from app.matching.engine import run_donor_matching
from app.matching.compatibility import is_preliminarily_compatible, evaluate_component_compatibility
from app.notifications.services import create_notification

hospital_bp = Blueprint('hospital', __name__, url_prefix='/hospital')


@hospital_bp.before_request
@login_required
@role_required('HOSPITAL')
def enforce_hospital_role():
    pass


@hospital_bp.route('/dashboard')
def dashboard():
    org = current_user.organization
    if not org:
        flash("No hospital organization affiliated with your account.", "danger")
        return redirect(url_for('main.index'))

    active_requests = BloodRequest.query.filter_by(requesting_organization_id=org.id)\
        .filter(BloodRequest.request_status.notin_(['FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED']))\
        .order_by(BloodRequest.created_at.desc()).all()

    past_requests = BloodRequest.query.filter_by(requesting_organization_id=org.id)\
        .filter(BloodRequest.request_status.in_(['FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED']))\
        .order_by(BloodRequest.created_at.desc()).limit(10).all()

    # Query responses from interested donors across this hospital's requests
    donor_responses = DonorRequestResponse.query.join(BloodRequest)\
        .filter(BloodRequest.requesting_organization_id == org.id)\
        .order_by(DonorRequestResponse.created_at.desc()).all()

    # Query direct invitations sent by this hospital
    sent_invitations = DonorInvitation.query.filter_by(hospital_id=org.id)\
        .order_by(DonorInvitation.created_at.desc()).all()

    return render_template(
        'hospital/dashboard.html',
        org=org,
        active_requests=active_requests,
        past_requests=past_requests,
        donor_responses=donor_responses,
        sent_invitations=sent_invitations
    )


@hospital_bp.route('/inventory-search')
@hospital_bp.route('/search-inventory')
def inventory_search():
    """Allows hospital staff to search real-time verified blood bank stock."""
    org = current_user.organization
    blood_group = request.args.get('blood_group', '').strip().upper()
    component = request.args.get('component_type', '').strip()
    state = request.args.get('state', '').strip()
    district = request.args.get('district', '').strip()

    query = BloodInventory.query.join(Organization)\
        .filter(Organization.verification_status.in_(['VERIFIED', 'APPROVED']))\
        .filter(BloodInventory.available_units > 0)

    if blood_group:
        query = query.filter(BloodInventory.blood_group == blood_group)
    if component:
        query = query.filter(BloodInventory.component_type == component)
    if state:
        query = query.filter(Organization.state == state)
    if district:
        query = query.filter(Organization.district == district)

    results = query.order_by(BloodInventory.available_units.desc()).limit(50).all()

    from app.locations import get_all_states
    return render_template(
        'hospital/inventory_search.html',
        org=org,
        results=results,
        selected_bg=blood_group,
        selected_comp=component,
        selected_state=state,
        selected_district=district,
        all_states=get_all_states()
    )


@hospital_bp.route('/find-donors')
def find_donors():
    """Find Matching Donors console: search registered donors, evaluate compatibility, and send requests."""
    org = current_user.organization
    if not org:
        flash("No hospital associated with your account.", "danger")
        return redirect(url_for('main.index'))

    blood_group = request.args.get('blood_group', '').strip().upper()
    component_type = request.args.get('component_type', 'Whole Blood').strip()
    max_dist_raw = request.args.get('max_distance', '').strip()
    availability = request.args.get('availability', 'available').strip().lower()
    query_search = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    max_distance_km = None
    if max_dist_raw:
        try:
            val = float(max_dist_raw)
            if val > 0:
                max_distance_km = val
        except ValueError:
            max_distance_km = None

    if availability not in ['available', 'all']:
        availability = 'available'

    # Search location and coordinates
    search_location_name = request.args.get('location_name', '').strip()
    lat_raw = request.args.get('lat', '').strip()
    lon_raw = request.args.get('lon', '').strip()

    search_lat = None
    search_lon = None
    if lat_raw and lon_raw:
        try:
            l_val = float(lat_raw)
            ln_val = float(lon_raw)
            if -90.0 <= l_val <= 90.0 and -180.0 <= ln_val <= 180.0:
                search_lat = l_val
                search_lon = ln_val
        except (ValueError, TypeError):
            search_lat = None
            search_lon = None

    # Offline/fallback lookup for standard Indian cities if name entered without autocomplete coords
    INDIAN_CITY_FALLBACK = {
        'kochi': (9.9312, 76.2673),
        'cochin': (9.9312, 76.2673),
        'bengaluru': (12.9716, 77.5946),
        'bangalore': (12.9716, 77.5946),
        'mumbai': (19.0760, 72.8777),
        'delhi': (28.6139, 77.2090),
        'new delhi': (28.6139, 77.2090),
        'chennai': (13.0827, 80.2707),
        'hyderabad': (17.3850, 78.4867),
        'kolkata': (22.5726, 88.3639),
        'pune': (18.5204, 73.8567),
        'ahmedabad': (23.0225, 72.5714),
        'thiruvananthapuram': (8.5241, 76.9366),
        'trivandrum': (8.5241, 76.9366),
        'kozhikode': (11.2588, 75.7804),
        'calicut': (11.2588, 75.7804),
        'jaipur': (26.9124, 75.7873),
        'lucknow': (26.8467, 80.9462),
        'chandigarh': (30.7333, 76.7794),
        'coimbatore': (11.0168, 76.9558),
        'mysuru': (12.2958, 76.6394),
        'mysore': (12.2958, 76.6394),
    }

    if search_lat is None and search_location_name:
        loc_lower = search_location_name.lower()
        for city_name, coords in INDIAN_CITY_FALLBACK.items():
            if city_name in loc_lower:
                search_lat, search_lon = coords
                break

    default_location_name = f"{org.city}, {org.state}" if org.city and org.state else (org.city or org.state or "Hospital Location")
    default_lat = org.latitude
    default_lon = org.longitude

    active_location_name = search_location_name if search_location_name else default_location_name
    active_lat = search_lat if search_lat is not None else default_lat
    active_lon = search_lon if search_lon is not None else default_lon
    is_custom_location = (search_lat is not None and search_lon is not None) and (
        (default_lat is None or default_lon is None) or 
        (round(search_lat, 3) != round(default_lat, 3) or round(search_lon, 3) != round(default_lon, 3))
    )

    from app.services.donor_matching_service import (
        search_matching_donors,
        SUPPORTED_COMPONENTS,
        VALID_BLOOD_GROUPS
    )

    results = search_matching_donors(
        hospital_org=org,
        blood_group=blood_group if blood_group in VALID_BLOOD_GROUPS else None,
        component_type=component_type if component_type in SUPPORTED_COMPONENTS else 'Whole Blood',
        max_distance_km=max_distance_km,
        availability_filter=availability,
        query_search=query_search or None,
        page=page,
        per_page=12,
        center_latitude=search_lat,
        center_longitude=search_lon,
        search_location_name=active_location_name
    )

    # Active verified blood requests for this hospital (to select in invitation modal)
    active_requests = BloodRequest.query.filter_by(requesting_organization_id=org.id)\
        .filter(BloodRequest.request_status.in_(['SUBMITTED', 'UNDER_REVIEW', 'VERIFIED', 'MATCHING', 'OPEN']))\
        .order_by(BloodRequest.created_at.desc()).all()

    return render_template(
        'hospital/find_donors.html',
        org=org,
        results=results,
        active_requests=active_requests,
        supported_components=SUPPORTED_COMPONENTS,
        valid_blood_groups=VALID_BLOOD_GROUPS,
        selected_blood_group=blood_group,
        selected_component=component_type,
        selected_distance=max_dist_raw,
        selected_availability=availability,
        search_query=query_search,
        selected_location_name=active_location_name,
        selected_lat=active_lat,
        selected_lon=active_lon,
        default_location_name=default_location_name,
        default_lat=default_lat,
        default_lon=default_lon,
        is_custom_location=is_custom_location
    )


@hospital_bp.route('/donor/<int:donor_id>/preview')
@verified_org_required
def donor_preview(donor_id):
    """Restricted donor profile preview for authorized clinical coordination."""
    org = current_user.organization
    donor = User.query.get_or_404(donor_id)

    if donor.role != 'DONOR' or not donor.donor_profile:
        abort(404)

    profile = donor.donor_profile
    if profile.verification_status not in ['APPROVED', 'VERIFIED'] and current_user.role != 'ADMIN':
        abort(403)

    # Calculate distance
    dist_km = None
    if org.latitude is not None and org.longitude is not None and profile.latitude is not None and profile.longitude is not None:
        from app.matching.engine import haversine_distance
        dist_km = haversine_distance(org.latitude, org.longitude, profile.latitude, profile.longitude)

    is_eligible, cooldown_days = profile.is_eligible_to_donate(cooldown_days=56)
    donation_count = donor.donations.filter_by(verification_status='VERIFIED').count()

    # Log audit event for accessing restricted donor clinical record
    AuditLog.log(
        action='VIEW_DONOR_PROFILE',
        entity_type='DonorProfile',
        entity_id=donor.id,
        details=f"Hospital '{org.organization_name}' accessed restricted profile preview for Donor #{donor.id}",
        actor_id=current_user.id,
        ip_address=get_client_ip()
    )
    db.session.commit()

    parts = donor.name.split()
    display_name = f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else donor.name

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
        from flask import jsonify
        return jsonify({
            'donor_id': donor.id,
            'donor_reference': f"DON-{donor.id:04d}",
            'display_name': display_name,
            'blood_group': profile.declared_blood_group,
            'city': profile.city or 'Not Specified',
            'district': profile.district or '',
            'state': profile.state or '',
            'distance_km': dist_km,
            'distance_display': f"{dist_km:.1f} km" if dist_km is not None else "Location not specified",
            'is_available': profile.availability_status,
            'is_verified': profile.verification_status in ('APPROVED', 'VERIFIED'),
            'cooldown_eligible': is_eligible,
            'cooldown_days_remaining': cooldown_days,
            'donation_count': donation_count,
            'notification_consent': profile.notification_consent
        })

    return render_template(
        'hospital/donor_preview.html',
        org=org,
        donor=donor,
        profile=profile,
        display_name=display_name,
        donor_reference=f"DON-{donor.id:04d}",
        distance_km=dist_km,
        is_eligible=is_eligible,
        cooldown_days=cooldown_days,
        donation_count=donation_count
    )


@hospital_bp.route('/send-invitation', methods=['POST'])
@verified_org_required
def send_invitation():
    """Dispatches a direct blood donation invitation from the matching donors interface."""
    org = current_user.organization
    donor_id = request.form.get('donor_id', type=int)
    request_id = request.form.get('blood_request_id', type=int)
    custom_message = request.form.get('message', '').strip()

    if not donor_id or not request_id:
        flash("Invalid request or donor reference specified.", "warning")
        return redirect(url_for('hospital.find_donors'))

    req = BloodRequest.query.get_or_404(request_id)
    if req.requesting_organization_id != org.id and current_user.role != 'ADMIN':
        abort(403)

    if req.request_status in ['FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED']:
        flash("Cannot send invitations for a closed, cancelled, or fulfilled request.", "warning")
        return redirect(url_for('hospital.find_donors'))

    donor = User.query.get_or_404(donor_id)
    if donor.role != 'DONOR' or not donor.is_active:
        abort(404)

    profile = donor.donor_profile
    if not profile or profile.verification_status not in ['APPROVED', 'VERIFIED']:
        flash("Invitations can only be dispatched to verified voluntary donors.", "warning")
        return redirect(url_for('hospital.find_donors'))

    if not profile.notification_consent:
        flash("This donor has opted out of direct emergency notifications.", "warning")
        return redirect(url_for('hospital.find_donors'))

    if not profile.availability_status:
        flash("This donor is currently marked as unavailable for donations.", "warning")
        return redirect(url_for('hospital.find_donors'))

    # Check component compatibility and clinical review
    eval_res = evaluate_component_compatibility(profile.declared_blood_group, req.blood_group, req.component_type)
    if eval_res['status'] == 'REQUIRES_CLINICAL_REVIEW':
        flash(f"Clinical Notice: Automated invitations cannot be dispatched for '{req.component_type}'. This component requires laboratory review by the attending pathologist.", "warning")
        return redirect(url_for('hospital.find_donors'))

    if not eval_res['is_compatible']:
        flash(f"Donor blood group ({profile.declared_blood_group}) is not compatible with request ({req.blood_group} {req.component_type}).", "warning")
        return redirect(url_for('hospital.find_donors'))

    # Prevent duplicate active invitations
    existing_inv = DonorInvitation.query.filter_by(
        donor_id=donor.id,
        blood_request_id=req.id
    ).first()

    try:
        if existing_inv:
            if existing_inv.invitation_status in ('SENT', 'DELIVERED', 'VIEWED', 'ACCEPTED'):
                flash(f"An active invitation has already been dispatched to {donor.name} (Status: {existing_inv.invitation_status}).", "info")
                return redirect(url_for('hospital.find_donors'))
            else:
                existing_inv.invitation_status = 'SENT'
                existing_inv.responded_at = None
                existing_inv.created_at = datetime.now(timezone.utc)
                existing_inv.message = custom_message or existing_inv.message
                inv = existing_inv
        else:
            inv = DonorInvitation(
                donor_id=donor.id,
                hospital_id=org.id,
                blood_request_id=req.id,
                invitation_status='SENT',
                message=custom_message or None,
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(inv)

        create_notification(
            recipient_id=donor.id,
            notification_type='HOSPITAL_INVITATION',
            title='Blood Donation Request',
            message=f"{org.organization_name} has invited you to donate for blood request {req.request_reference} ({req.blood_group}, {req.urgency_level} Priority)."
        )

        AuditLog.log(
            action='HOSPITAL_INVITATION',
            entity_type='DonorInvitation',
            entity_id=req.id,
            details=f"Hospital {org.organization_name} sent invitation to donor #{donor.id} for request {req.request_reference}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )

        db.session.commit()
        flash(f"Blood donation request invitation successfully dispatched to {donor.name}.", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Send Invitation Error]: {e}")
        flash("Could not send donation invitation at this time.", "danger")

    return redirect(request.referrer or url_for('hospital.find_donors'))


@hospital_bp.route('/request/new', methods=['GET', 'POST'])
@verified_org_required
def create_request():
    org = current_user.organization

    if not org or not org.is_verified or org.verification_status == 'SUSPENDED':
        flash("Unauthorized: Facility is unverified or currently suspended. Blood requests cannot be created.", "danger")
        return redirect(url_for('hospital.dashboard'))

    if request.method == 'POST':
        blood_group = request.form.get('blood_group', '').strip().upper()
        component_type = request.form.get('component_type', 'Whole Blood').strip()
        units_val = request.form.get('units_required', '1').strip()
        try:
            units_required = int(units_val)
        except ValueError:
            units_required = 1

        urgency_level = request.form.get('urgency_level', 'HIGH').strip().upper()
        location = request.form.get('location', f"{org.organization_name}, {org.city}").strip()
        contact_phone = request.form.get('contact_phone', org.contact_phone).strip()
        patient_name = request.form.get('patient_name', '').strip() or None
        patient_reference = request.form.get('patient_reference', '').strip() or None
        additional_notes = request.form.get('additional_notes', '').strip()
        deadline_str = request.form.get('clinical_deadline', '').strip()

        # Strict server-side validation
        from app.services.donor_matching_service import VALID_BLOOD_GROUPS, SUPPORTED_COMPONENTS
        if blood_group not in VALID_BLOOD_GROUPS:
            flash(f"Invalid Blood Group: '{blood_group}' is not a recognized ABO/Rh blood group.", "warning")
            return render_template('hospital/create_request.html', org=org)

        if component_type not in SUPPORTED_COMPONENTS:
            flash(f"Unsupported Component: '{component_type}' is not supported for clinical procurement.", "warning")
            return render_template('hospital/create_request.html', org=org)

        if units_required < 1 or units_required > 50:
            flash("Units required must be between 1 and 50 units.", "warning")
            return render_template('hospital/create_request.html', org=org)

        if not location:
            flash("Delivery location is mandatory for clinical dispatch.", "warning")
            return render_template('hospital/create_request.html', org=org)

        clinical_deadline = None
        if deadline_str:
            try:
                clinical_deadline = datetime.fromisoformat(deadline_str)
                dl = clinical_deadline
                if dl.tzinfo is None:
                    dl = dl.replace(tzinfo=timezone.utc)
                if dl < datetime.now(timezone.utc):
                    flash("Clinical deadline cannot be in the past.", "warning")
                    return render_template('hospital/create_request.html', org=org)
            except ValueError:
                pass

        from app.locations import is_valid_state, is_valid_district
        req_state = request.form.get('state', org.state or '').strip()
        req_district = request.form.get('district', org.district or '').strip()
        req_city = request.form.get('city', org.city or '').strip()

        if req_state and not is_valid_state(req_state):
            flash(f"Invalid State: '{req_state}' is not a recognized Indian State or Union Territory.", "warning")
            return render_template('hospital/create_request.html', org=org)

        if req_state and req_district and not is_valid_district(req_state, req_district):
            flash(f"Invalid District: '{req_district}' is not an administrative district of {req_state}.", "warning")
            return render_template('hospital/create_request.html', org=org)

        # Duplicate submission protection (within 60 seconds)
        recent_dup = BloodRequest.query.filter(
            BloodRequest.requesting_organization_id == org.id,
            BloodRequest.blood_group == blood_group,
            BloodRequest.component_type == component_type,
            BloodRequest.units_required == units_required,
            BloodRequest.location == location,
            BloodRequest.request_status.notin_(['FULFILLED', 'REJECTED', 'CANCELLED']),
            BloodRequest.created_at >= datetime.now(timezone.utc) - timedelta(seconds=60)
        ).first()
        if recent_dup:
            flash(f"Duplicate submission detected: Request {recent_dup.request_reference} was recently submitted.", "info")
            return redirect(url_for('hospital.request_details', request_id=recent_dup.id))

        reference = BloodRequest.generate_reference()

        # Direct activation: verified hospital requests are immediately validated and enter active matching
        new_req = BloodRequest(
            request_reference=reference,
            requesting_organization_id=org.id,
            blood_group=blood_group,
            component_type=component_type,
            units_required=units_required,
            location=location,
            country="India",
            state=req_state,
            district=req_district,
            city=req_city,
            latitude=org.latitude,
            longitude=org.longitude,
            urgency_level=urgency_level,
            clinical_deadline=clinical_deadline,
            patient_name=patient_name,
            patient_reference=patient_reference,
            additional_notes=additional_notes,
            contact_phone=contact_phone,
            verification_status='VERIFIED',
            request_status='ACTIVE_MATCHING'
        )

        try:
            db.session.add(new_req)
            db.session.flush()

            # Calculate initial trusted priority score
            update_request_priority(new_req)

            # 1. Trigger smart donor matching and create persistent invitations for eligible donors
            from app.matching.engine import run_donor_matching, find_suitable_blood_banks
            matches = []
            matching_error = None
            try:
                matches = run_donor_matching(new_req, notify_donors=True)
            except Exception as me:
                matching_error = str(me)
                import logging
                logging.getLogger(__name__).warning(f"[Donor Matching Warning]: {me}")

            # 2. Identify suitable blood banks using inventory, component compatibility, and location
            bank_match = {'suitable_banks': [], 'banks_with_stock_count': 0, 'total_compatible_units': 0, 'regional_banks_count': 0}
            try:
                bank_match = find_suitable_blood_banks(new_req)
            except Exception as be:
                import logging
                logging.getLogger(__name__).warning(f"[Blood Bank Matching Warning]: {be}")

            # 3. Notify suitable blood banks
            banks_to_notify = []
            # Prioritize banks with stock, or fall back to local regional banks
            for b_info in bank_match.get('suitable_banks', []):
                if b_info['has_stock'] or b_info.get('is_in_range', False):
                    banks_to_notify.append(b_info['bank'])

            # If no banks identified via engine, fallback to all verified banks
            if not banks_to_notify:
                banks_to_notify = Organization.query.filter(
                    Organization.organization_type == 'BLOOD_BANK',
                    Organization.verification_status.in_(['VERIFIED', 'APPROVED']),
                    Organization.id != org.id
                ).all()

            banks_notified_count = 0
            for bank in banks_to_notify:
                for membership in bank.memberships:
                    try:
                        create_notification(
                            recipient_id=membership.user_id,
                            notification_type='HOSPITAL_BLOOD_REQUEST',
                            title=f"Active Hospital Request: {blood_group} ({urgency_level})",
                            message=f"Verified hospital {org.organization_name} has an active requirement for {units_required} unit(s) of {blood_group} {component_type}. Immediate stock coordination is open."
                        )
                        banks_notified_count += 1
                    except Exception:
                        pass

            donors_found = len(matches)
            from app.models.communication import DonorInvitation
            invitations_created = DonorInvitation.query.filter_by(blood_request_id=new_req.id).count()
            banks_with_stock = bank_match.get('banks_with_stock_count', 0)
            compatible_units = bank_match.get('total_compatible_units', 0)

            # Record delivery and processing outcomes for diagnostics
            diag_summary = (
                f"[Dispatch Diagnostics] Donors matched: {donors_found} (Invitations: {invitations_created}). "
                f"Banks with stock: {banks_with_stock} (Units: {compatible_units}). "
                f"Facilities notified: {banks_notified_count}."
            )
            if new_req.additional_notes:
                new_req.additional_notes = f"{new_req.additional_notes} | {diag_summary}"
            else:
                new_req.additional_notes = diag_summary

            AuditLog.log(
                action='CREATE_BLOOD_REQUEST',
                entity_type='BloodRequest',
                entity_id=new_req.id,
                details=f"Reference {reference} for {units_required} unit(s) of {blood_group} {component_type} activated for matching. {diag_summary}",
                actor_id=current_user.id,
                ip_address=get_client_ip()
            )

            db.session.commit()

            # Diagnostic summary for hospital staff
            donor_res_text = f"{donors_found} matching donor(s) found ({invitations_created} invitations dispatched)" if donors_found > 0 else "No eligible donors found in vicinity"
            bank_res_text = f"{banks_with_stock} blood bank(s) with stock found ({compatible_units} units available)" if banks_with_stock > 0 else "No suitable inventory found in regional banks"

            flash(
                f"Emergency Blood Request {reference} created and activated for matching. "
                f"Hospital, blood bank, and donor coordination is now active. "
                f"Delivery results: {donor_res_text}; {bank_res_text}.",
                "success"
            )
            return redirect(url_for('hospital.request_details', request_id=new_req.id))
        except Exception as e:
            db.session.rollback()
            import logging
            logging.getLogger(__name__).error(f"[Hospital Request Error] Failed to persist request {reference}: {e}")
            flash("Database error occurred while submitting your emergency request. Please try again.", "danger")
            return render_template('hospital/create_request.html', org=org)

    return render_template('hospital/create_request.html', org=org)


@hospital_bp.route('/request/<int:request_id>')
def request_details(request_id):
    org = current_user.organization
    req = BloodRequest.query.get_or_404(request_id)

    # Check ownership unless admin (IDOR protection)
    if req.requesting_organization_id != org.id and current_user.role != 'ADMIN':
        abort(403)

    matches = req.matches.order_by(DonorMatch.match_score.desc()).all()
    responses = req.donor_responses.order_by(DonorRequestResponse.created_at.desc()).all()
    invitations = req.invitations.order_by(DonorInvitation.created_at.desc()).all()
    bank_responses = req.bank_responses.order_by(BloodBankResponse.created_at.desc()).all()

    # Patient name retrieval respecting clinical privacy
    patient_name = req.get_patient_name(current_user)

    return render_template(
        'hospital/request_details.html',
        req=req,
        matches=matches,
        responses=responses,
        invitations=invitations,
        bank_responses=bank_responses,
        patient_name=patient_name,
        org=org
    )


@hospital_bp.route('/request/<int:request_id>/invite-donor/<int:donor_id>', methods=['POST'])
@verified_org_required
def invite_donor(request_id, donor_id):
    """'Send Blood Donation Request' action handler to invite consented, compatible donors."""
    org = current_user.organization
    req = BloodRequest.query.get_or_404(request_id)

    if req.requesting_organization_id != org.id and current_user.role != 'ADMIN':
        abort(403)

    if not req.is_active:
        flash("Cannot dispatch invitations for an inactive or closed request.", "warning")
        return redirect(url_for('hospital.request_details', request_id=req.id))

    donor = User.query.get_or_404(donor_id)
    if donor.role != 'DONOR' or not donor.is_active:
        flash("Target account is not an active voluntary donor.", "warning")
        return redirect(url_for('hospital.request_details', request_id=req.id))

    profile = donor.donor_profile
    if not profile or profile.verification_status not in ['APPROVED', 'VERIFIED']:
        flash("Invitations can only be dispatched to verified voluntary donors.", "warning")
        return redirect(url_for('hospital.request_details', request_id=req.id))

    if not profile.notification_consent:
        flash("This donor has opted out of receiving direct donation requests.", "warning")
        return redirect(url_for('hospital.request_details', request_id=req.id))

    if not profile.availability_status:
        flash("This donor is currently marked as unavailable for donations.", "warning")
        return redirect(url_for('hospital.request_details', request_id=req.id))

    # Preliminary component-aware compatibility check
    eval_res = evaluate_component_compatibility(profile.declared_blood_group, req.blood_group, req.component_type)
    if eval_res['status'] == 'REQUIRES_CLINICAL_REVIEW':
        flash(f"Clinical Notice: Automated invitations cannot be dispatched for '{req.component_type}'. This component requires laboratory review by the attending pathologist.", "warning")
        return redirect(url_for('hospital.request_details', request_id=req.id))

    if not eval_res['is_compatible']:
        flash(f"Donor blood group ({profile.declared_blood_group}) is not compatible with request ({req.blood_group} {req.component_type}).", "warning")
        return redirect(url_for('hospital.request_details', request_id=req.id))

    # Duplicate invitation prevention
    existing_inv = DonorInvitation.query.filter_by(
        donor_id=donor.id,
        blood_request_id=req.id
    ).first()

    custom_message = request.form.get('invitation_message', '').strip()

    try:
        if existing_inv:
            if existing_inv.invitation_status in ('SENT', 'DELIVERED', 'VIEWED', 'ACCEPTED'):
                flash(f"An active invitation has already been dispatched to {donor.name} (Status: {existing_inv.invitation_status}).", "info")
                return redirect(url_for('hospital.request_details', request_id=req.id))
            else:
                existing_inv.invitation_status = 'SENT'
                existing_inv.responded_at = None
                existing_inv.created_at = datetime.now(timezone.utc)
                existing_inv.message = custom_message or existing_inv.message
                inv = existing_inv
        else:
            inv = DonorInvitation(
                donor_id=donor.id,
                hospital_id=org.id,
                blood_request_id=req.id,
                invitation_status='SENT',
                message=custom_message or None,
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(inv)

        create_notification(
            recipient_id=donor.id,
            notification_type='HOSPITAL_INVITATION',
            title='Blood Donation Request',
            message=f"{org.organization_name} has invited you to donate for blood request {req.request_reference} ({req.blood_group}, {req.urgency_level} Priority)."
        )

        AuditLog.log(
            action='HOSPITAL_INVITATION',
            entity_type='DonorInvitation',
            entity_id=req.id,
            details=f"Hospital {org.organization_name} sent invitation to donor {donor.email} for request {req.request_reference}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )

        db.session.commit()
        flash(f"Blood donation request invitation successfully dispatched to {donor.name}.", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Invite Donor Error]: {e}")
        flash("Could not send donation invitation at this time.", "danger")

    return redirect(url_for('hospital.request_details', request_id=req.id))


@hospital_bp.route('/response/<int:response_id>/status', methods=['POST'])
def update_donor_response_status(response_id):
    """Allows hospital clinical staff to update the progress of an interested donor."""
    org = current_user.organization
    resp = DonorRequestResponse.query.get_or_404(response_id)

    # Ownership / IDOR check
    if resp.blood_request.requesting_organization_id != org.id and current_user.role != 'ADMIN':
        abort(403)

    new_status = request.form.get('response_status', '').strip().upper()
    allowed_statuses = {'INTERESTED', 'CONTACT_REQUESTED', 'CONTACTED', 'CONFIRMED', 'COMPLETED', 'DECLINED'}

    if new_status not in allowed_statuses:
        flash("Invalid status transition.", "warning")
        return redirect(url_for('hospital.request_details', request_id=resp.blood_request_id))

    try:
        resp.response_status = new_status
        resp.updated_at = datetime.now(timezone.utc)

        # Notify donor
        create_notification(
            recipient_id=resp.donor_id,
            notification_type='RESPONSE_STATUS_UPDATE',
            title='Donation Status Updated',
            message=f"{org.organization_name} updated your donation status to '{new_status}' for request {resp.blood_request.request_reference}."
        )

        AuditLog.log(
            action='UPDATE_DONOR_RESPONSE_STATUS',
            entity_type='DonorRequestResponse',
            entity_id=resp.id,
            details=f"Status updated to {new_status} for donor User #{resp.donor_id}",
            actor_id=current_user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()
        flash(f"Donor response status updated to {new_status}.", "success")
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Update Donor Response Status Error]: {e}")
        flash("Could not update donor response status.", "danger")

    return redirect(request.referrer or url_for('hospital.dashboard'))


@hospital_bp.route('/request/<int:request_id>/cancel', methods=['POST'])
def cancel_request(request_id):
    org = current_user.organization
    req = BloodRequest.query.get_or_404(request_id)

    if req.requesting_organization_id != org.id and current_user.role != 'ADMIN':
        abort(403)

    if req.request_status in ['FULFILLED', 'REJECTED', 'CANCELLED']:
        flash("This request cannot be cancelled in its current state.", "info")
        return redirect(url_for('hospital.dashboard'))

    try:
        req.request_status = 'CANCELLED'
        AuditLog.log(
            action='CANCEL_BLOOD_REQUEST',
            entity_type='BloodRequest',
            entity_id=req.id,
            actor_id=current_user.id
        )
        db.session.commit()
        flash(f"Request {req.request_reference} has been cancelled.", "warning")
    except Exception:
        db.session.rollback()
        flash("Could not cancel request at this time.", "danger")
    return redirect(url_for('hospital.dashboard'))


@hospital_bp.route('/request/<int:request_id>/update-status', methods=['POST'])
def update_request_status(request_id):
    org = current_user.organization
    req = BloodRequest.query.get_or_404(request_id)

    if req.requesting_organization_id != org.id and current_user.role != 'ADMIN':
        abort(403)

    new_status = request.form.get('request_status', '').strip().upper()
    allowed_statuses = ['FULFILLED', 'CANCELLED', 'UNDER_REVIEW', 'MATCHING', 'ACTIVE_MATCHING', 'PARTIALLY_FULFILLED']
    if new_status not in allowed_statuses:
        flash("Invalid request status transition.", "warning")
        return redirect(url_for('hospital.request_details', request_id=req.id))

    try:
        req.request_status = new_status
        req.updated_at = datetime.now(timezone.utc)
        AuditLog.log(
            action='UPDATE_REQUEST_STATUS',
            entity_type='BloodRequest',
            entity_id=req.id,
            details=f"Status updated to {new_status}",
            actor_id=current_user.id
        )
        db.session.commit()
        flash(f"Request {req.request_reference} status has been updated to {new_status}.", "success")
    except Exception:
        db.session.rollback()
        flash("Could not update request status.", "danger")
    return redirect(url_for('hospital.request_details', request_id=req.id))


@hospital_bp.route('/request/<int:request_id>/match', methods=['POST'])
@verified_org_required
def trigger_matching(request_id):
    org = current_user.organization
    req = BloodRequest.query.get_or_404(request_id)

    if req.requesting_organization_id != org.id and current_user.role != 'ADMIN':
        abort(403)

    if req.verification_status != 'VERIFIED':
        flash("Smart donor matching requires the blood request to be verified by administrators.", "warning")
        return redirect(url_for('hospital.request_details', request_id=req.id))

    try:
        update_request_priority(req)
        matches = run_donor_matching(req, notify_donors=True)
        req.request_status = 'MATCHING'
        db.session.commit()
        flash(f"Matching executed: Found {len(matches)} preliminary compatible donor(s).", "success")
    except Exception:
        db.session.rollback()
        flash("Matching execution encountered an error.", "danger")
    return redirect(url_for('hospital.request_details', request_id=req.id))


@hospital_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    org = current_user.organization
    if not org:
        flash("No hospital associated with your account.", "danger")
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
            return render_template('hospital/profile.html', org=org)
        if new_state and new_district and not is_valid_district(new_state, new_district):
            flash(f"Invalid District: '{new_district}'.", "warning")
            return render_template('hospital/profile.html', org=org)

        try:
            org.contact_phone = new_phone
            org.contact_email = new_email
            org.address = new_address
            org.state = new_state
            org.district = new_district
            org.city = new_city
            org.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            flash("Hospital profile and facility contact details updated successfully.", "success")
            return redirect(url_for('hospital.dashboard'))
        except Exception:
            db.session.rollback()
            flash("An error occurred while updating hospital profile.", "danger")

    return render_template('hospital/profile.html', org=org)

