from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.organization import Organization
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.donation import Donation
from app.models.notification import Notification

main_bp = Blueprint('main', __name__)


def extract_blood_group_arg(req, param_name='blood_group'):
    """Extract blood group filter handling '+' URL query decoding cleanly."""
    val = (req.args.get(param_name) or '').strip().upper()
    if val in ['ALL', 'ANY', 'SHOW ALL', 'ANY GROUP', 'ALL BLOOD GROUPS', 'NONE']:
        return ''
    if not val:
        return ''
    if '+' in val or '-' in val:
        return val
    import re
    raw_qs = req.query_string.decode('utf-8', errors='ignore')
    m = re.search(re.escape(param_name) + r'=(?:%20|\+)?' + re.escape(val) + r'(?:\+|\%2B)', raw_qs, re.IGNORECASE)
    if m:
        return f"{val}+"
    return val


@main_bp.route('/login', methods=['GET', 'POST'])
def root_login():
    """Dedicated top-level /login route."""
    from app.auth.routes import login
    return login()


@main_bp.route('/register', methods=['GET', 'POST'])
def root_register():
    """Dedicated top-level /register route."""
    from app.auth.routes import register
    return register()


@main_bp.route('/')
def index():
    from app.locations import get_all_states
    total_donors = User.query.filter_by(role='DONOR').count()
    total_banks = Organization.query.filter_by(organization_type='BLOOD_BANK', verification_status='VERIFIED').count()
    total_hospitals = Organization.query.filter_by(organization_type='HOSPITAL', verification_status='VERIFIED').count()
    verified_donations = Donation.query.filter_by(verification_status='VERIFIED').count()

    participating_banks = Organization.query.filter_by(organization_type='BLOOD_BANK', verification_status='VERIFIED').limit(8).all()
    recent_requests = BloodRequest.query.filter(
        BloodRequest.verification_status == 'VERIFIED',
        BloodRequest.request_status.in_(['VERIFIED', 'MATCHING'])
    ).order_by(BloodRequest.priority_score.desc()).limit(4).all()

    total_units_reported = db.session.query(db.func.coalesce(db.func.sum(BloodInventory.available_units), 0)).scalar() or 0

    return render_template(
        'index.html',
        total_donors=total_donors,
        total_banks=total_banks,
        total_hospitals=total_hospitals,
        verified_donations=verified_donations,
        participating_banks=participating_banks,
        recent_requests=recent_requests,
        total_units_reported=total_units_reported,
        all_indian_states=get_all_states()
    )


@main_bp.route('/search')
def search():
    from app.locations import get_districts_for_state, is_valid_state, is_valid_district

    state_filter = request.args.get('state', '').strip()
    district_filter = request.args.get('district', '').strip()
    city_filter = request.args.get('city', '').strip()
    group_filter = request.args.get('blood_group', '').strip().upper()
    if group_filter in ['ALL', 'ANY', 'SHOW ALL', 'ANY GROUP', 'ALL BLOOD GROUPS', 'NONE']:
        group_filter = ''

    comp_filter = request.args.get('component_type', '').strip() or request.args.get('component', '').strip()
    if comp_filter.upper() in ['ALL', 'ANY', 'ALL COMPONENTS', 'NONE']:
        comp_filter = ''

    scope = request.args.get('scope', 'district').strip().lower()  # 'district', 'state', 'all_india'
    units_filter = request.args.get('units', type=int)

    # Server-side pagination and view mode
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    if per_page not in [12, 24, 48]:
        per_page = 12
    view_mode = request.args.get('view', 'cards').strip().lower()
    if view_mode not in ['cards', 'table']:
        view_mode = 'cards'

    # Server-side validation of State & District relationship
    validation_warning = None
    if state_filter and not is_valid_state(state_filter):
        validation_warning = f"'{state_filter}' is not recognized as a valid Indian State or Union Territory."
        state_filter = ''
        district_filter = ''
    elif state_filter and district_filter and not is_valid_district(state_filter, district_filter):
        validation_warning = f"'{district_filter}' is not an administrative district of {state_filter}. District filter was reset."
        district_filter = ''

    if validation_warning:
        flash(validation_warning, "warning")

    query = db.session.query(BloodInventory, Organization)\
        .join(Organization, BloodInventory.blood_bank_id == Organization.id)\
        .filter(Organization.verification_status == 'VERIFIED')

    # Apply Scope and Location Filters
    if scope != 'all_india':
        if state_filter:
            query = query.filter(Organization.state.ilike(f"%{state_filter}%"))
        if district_filter and scope == 'district':
            query = query.filter(Organization.district.ilike(f"%{district_filter}%"))
        if city_filter:
            query = query.filter(Organization.city.ilike(f"%{city_filter}%"))

    if group_filter:
        query = query.filter(BloodInventory.blood_group == group_filter)
    if comp_filter:
        query = query.filter(BloodInventory.component_type == comp_filter)
    if units_filter and units_filter > 0:
        query = query.filter(BloodInventory.available_units >= units_filter)

    pagination = query.order_by(BloodInventory.available_units.desc()).paginate(page=page, per_page=per_page, error_out=False)
    results = pagination.items

    available_districts = get_districts_for_state(state_filter) if state_filter else []

    return render_template(
        'search.html',
        results=results,
        pagination=pagination,
        total_count=pagination.total,
        page=page,
        per_page=per_page,
        view_mode=view_mode,
        selected_state=state_filter,
        selected_district=district_filter,
        selected_city=city_filter,
        selected_group=group_filter,
        selected_comp=comp_filter,
        selected_scope=scope,
        units_filter=units_filter or 1,
        available_districts=available_districts
    )


# =========================================================================
# Location REST API Endpoints (Reusable for all forms & dynamic dropdowns)
# =========================================================================

@main_bp.route('/api/locations/states')
def api_locations_states():
    from app.locations import get_all_states, get_states_only, get_union_territories_only
    return jsonify({
        'states': get_all_states(),
        'states_only': get_states_only(),
        'union_territories': get_union_territories_only(),
        'count': len(get_all_states())
    })


@main_bp.route('/api/locations/districts')
def api_locations_districts():
    from app.locations import get_districts_for_state
    state = request.args.get('state', '').strip()
    districts = get_districts_for_state(state)
    return jsonify({
        'state': state,
        'districts': districts,
        'count': len(districts)
    })


@main_bp.route('/api/locations/hierarchy')
def api_locations_hierarchy():
    from app.locations import get_all_locations_hierarchy
    return jsonify(get_all_locations_hierarchy())


@main_bp.route('/api/locations/validate', methods=['GET', 'POST'])
def api_locations_validate():
    from app.locations import is_valid_state, is_valid_district
    if request.method == 'GET':
        state = request.args.get('state', '').strip()
        district = request.args.get('district', '').strip()
    else:
        data = request.get_json(silent=True) or request.form
        state = data.get('state', '').strip() if data else ''
        district = data.get('district', '').strip() if data else ''

    valid_state = is_valid_state(state)
    valid_district = is_valid_district(state, district) if district else True

    return jsonify({
        'valid_state': valid_state,
        'valid_district': valid_district,
        'valid': valid_state and valid_district
    })


@main_bp.route('/api/locations/banks-by-location')
def api_banks_by_location():
    state = request.args.get('state', '').strip()
    district = request.args.get('district', '').strip()

    query = Organization.query.filter_by(organization_type='BLOOD_BANK', verification_status='VERIFIED')
    if state:
        query = query.filter(Organization.state.ilike(f"%{state}%"))
    if district:
        query = query.filter(Organization.district.ilike(f"%{district}%"))

    banks = query.all()
    results = []
    for b in banks:
        results.append({
            'id': b.id,
            'name': b.organization_name,
            'state': b.state,
            'district': b.district,
            'city': b.city,
            'address': b.address,
            'phone': b.contact_phone,
            'total_units': b.total_reported_units,
            'lat': b.latitude,
            'lng': b.longitude
        })
    return jsonify({'banks': results, 'count': len(results)})



@main_bp.route('/map')
def map_view():
    verified_banks = Organization.query.filter_by(
        organization_type='BLOOD_BANK',
        verification_status='VERIFIED'
    ).all()

    banks_json = []
    for b in verified_banks:
        if b.latitude and b.longitude:
            banks_json.append({
                'id': b.id,
                'name': b.organization_name,
                'city': b.city,
                'district': b.district,
                'state': b.state,
                'address': b.address,
                'phone': b.contact_phone,
                'lat': b.latitude,
                'lng': b.longitude,
                'total_units': b.total_reported_units
            })

    return render_template('map.html', banks_json=banks_json)


@main_bp.route('/about')
def about():
    return render_template('about.html')


@main_bp.route('/how-it-works')
def how_it_works():
    return render_template('how_it_works.html')


@main_bp.route('/notifications/read/<int:notif_id>', methods=['POST'])
@login_required
def read_notification(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    if notif.recipient_id == current_user.id:
        notif.mark_as_read()
        db.session.commit()
    return redirect(request.referrer or url_for('main.index'))


@main_bp.route('/blood-banks')
def blood_banks():
    from app.locations import get_all_states, get_districts_for_state
    state_filter = request.args.get('state', '').strip()
    district_filter = request.args.get('district', '').strip()
    city_filter = request.args.get('city', '').strip()
    q = request.args.get('q', '').strip()
    group_filter = request.args.get('blood_group', '').strip().upper()
    if group_filter in ['ALL', 'ANY', 'SHOW ALL', 'ANY GROUP', 'ALL BLOOD GROUPS', 'NONE']:
        group_filter = ''

    # Server-side pagination and view mode
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    if per_page not in [12, 24, 48]:
        per_page = 12
    view_mode = request.args.get('view', 'cards').strip().lower()
    if view_mode not in ['cards', 'table']:
        view_mode = 'cards'

    query = Organization.query.filter_by(
        organization_type='BLOOD_BANK',
        verification_status='VERIFIED'
    )

    if q:
        query = query.filter(
            db.or_(
                Organization.organization_name.ilike(f"%{q}%"),
                Organization.address.ilike(f"%{q}%"),
                Organization.city.ilike(f"%{q}%")
            )
        )
    if state_filter:
        query = query.filter(Organization.state.ilike(f"%{state_filter}%"))
    if district_filter:
        query = query.filter(Organization.district.ilike(f"%{district_filter}%"))
    if city_filter:
        query = query.filter(Organization.city.ilike(f"%{city_filter}%"))

    if group_filter:
        query = query.join(BloodInventory, BloodInventory.blood_bank_id == Organization.id)\
                     .filter(BloodInventory.blood_group == group_filter, BloodInventory.available_units > 0)

    # All verified banks for map coordinates
    all_banks_for_map = query.all()
    banks_json = []
    for b in all_banks_for_map:
        if b.latitude and b.longitude:
            banks_json.append({
                'id': b.id,
                'name': b.organization_name,
                'city': b.city,
                'district': b.district,
                'state': b.state,
                'address': b.address,
                'phone': b.contact_phone,
                'lat': b.latitude,
                'lng': b.longitude,
                'total_units': b.total_reported_units
            })

    pagination = query.order_by(Organization.organization_name.asc()).paginate(page=page, per_page=per_page, error_out=False)
    banks = pagination.items

    banks_data = []
    for b in banks:
        invs = BloodInventory.query.filter_by(blood_bank_id=b.id).all()
        inv_map = {inv.blood_group: inv.available_units for inv in invs}
        banks_data.append({
            'org': b,
            'inventory_map': inv_map,
            'total_units': b.total_reported_units
        })

    available_districts = get_districts_for_state(state_filter) if state_filter else []

    return render_template(
        'blood_banks.html',
        banks_data=banks_data,
        banks_json=banks_json,
        pagination=pagination,
        total_count=pagination.total,
        page=page,
        per_page=per_page,
        view_mode=view_mode,
        selected_state=state_filter,
        selected_district=district_filter,
        selected_city=city_filter,
        selected_group=group_filter,
        search_query=q,
        all_indian_states=get_all_states(),
        available_districts=available_districts
    )


@main_bp.route('/become-a-donor')
@main_bp.route('/donors')
def donors():
    from app.locations import get_all_states
    donor_profile = None
    balance = 0
    recent_donations = []
    is_eligible = True
    cooldown_days = 0

    if current_user.is_authenticated and current_user.role == 'DONOR':
        donor_profile = DonorProfile.query.filter_by(user_id=current_user.id).first()
        if donor_profile:
            balance = current_user.reward_balance
            is_eligible, cooldown_days = donor_profile.is_eligible_to_donate()
            recent_donations = Donation.query.filter_by(donor_id=current_user.id)\
                .order_by(Donation.donation_date.desc()).limit(3).all()

    total_registered_donors = User.query.filter_by(role='DONOR').count()
    total_verified_donations = Donation.query.filter_by(verification_status='VERIFIED').count()

    return render_template(
        'donors.html',
        donor_profile=donor_profile,
        balance=balance,
        is_eligible=is_eligible,
        cooldown_days=cooldown_days,
        recent_donations=recent_donations,
        total_registered_donors=total_registered_donors,
        total_verified_donations=total_verified_donations,
        all_indian_states=get_all_states()
    )


@main_bp.route('/emergency-requests')
@main_bp.route('/requests')
def emergency_requests():
    from app.locations import get_all_states
    from app.matching.compatibility import evaluate_component_compatibility
    from app.models.communication import DonorRequestResponse, DonorInvitation

    state_filter = request.args.get('state', '').strip()
    group_filter = extract_blood_group_arg(request, 'blood_group')
    urgency_filter = request.args.get('urgency', '').strip().upper()

    # Server-side pagination and view mode
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    if per_page not in [12, 24, 48]:
        per_page = 12
    view_mode = request.args.get('view', 'cards').strip().lower()
    if view_mode not in ['cards', 'table']:
        view_mode = 'cards'

    active_statuses = [
        'ACTIVE_MATCHING', 'MATCHING', 'VERIFIED', 'OPEN',
        'BLOOD_BANK_RESPONDED', 'DONOR_RESPONDED', 'PARTIALLY_FULFILLED'
    ]
    query = BloodRequest.query.filter(
        BloodRequest.verification_status == 'VERIFIED',
        BloodRequest.request_status.in_(active_statuses)
    )

    if state_filter:
        query = query.filter(BloodRequest.state.ilike(f"%{state_filter}%"))
    if group_filter:
        query = query.filter(BloodRequest.blood_group == group_filter)
    if urgency_filter:
        query = query.filter(BloodRequest.urgency_level == urgency_filter)

    pagination = query.order_by(BloodRequest.priority_score.desc()).paginate(page=page, per_page=per_page, error_out=False)
    requests_list = pagination.items

    donor_profile = None
    is_eligible = True
    cooldown_days = 0
    donor_responses = {}
    donor_invitations = {}

    if current_user.is_authenticated and current_user.role == 'DONOR':
        donor_profile = current_user.donor_profile
        if donor_profile:
            is_eligible, cooldown_days = donor_profile.is_eligible_to_donate()
            resp_list = DonorRequestResponse.query.filter_by(donor_id=current_user.id).all()
            donor_responses = {r.blood_request_id: r for r in resp_list}
            inv_list = DonorInvitation.query.filter_by(donor_id=current_user.id).all()
            donor_invitations = {inv.blood_request_id: inv for inv in inv_list}

    for req in requests_list:
        if donor_profile:
            req.compatibility_info = evaluate_component_compatibility(
                donor_profile.declared_blood_group,
                req.blood_group,
                req.component_type
            )
            req.donor_response = donor_responses.get(req.id)
            req.donor_invitation = donor_invitations.get(req.id)
        else:
            req.compatibility_info = None
            req.donor_response = None
            req.donor_invitation = None

    return render_template(
        'requests.html',
        requests=requests_list,
        pagination=pagination,
        total_count=pagination.total,
        page=page,
        per_page=per_page,
        view_mode=view_mode,
        selected_state=state_filter,
        selected_group=group_filter,
        selected_urgency=urgency_filter,
        all_indian_states=get_all_states(),
        donor_profile=donor_profile,
        is_eligible=is_eligible,
        cooldown_days=cooldown_days
    )
