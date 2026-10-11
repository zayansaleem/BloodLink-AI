"""
Donor Matching Service for BloodLink AI.
Provides medical-grade preliminary donor candidate filtering, compatibility evaluation,
distance calculation, and eligibility scoring for hospital procurement.
"""

import math
from datetime import datetime, date, timezone
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization
from app.matching.compatibility import is_preliminarily_compatible, get_compatible_donor_groups
from app.matching.engine import haversine_distance


SUPPORTED_COMPONENTS = [
    'Whole Blood',
    'Red Blood Cells',
    'Platelets',
    'Plasma'
]

VALID_BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']


def search_matching_donors(
    hospital_org: Organization,
    blood_group: str = None,
    component_type: str = 'Whole Blood',
    max_distance_km: float = None,
    availability_filter: str = 'available',
    query_search: str = None,
    page: int = 1,
    per_page: int = 12,
    center_latitude: float = None,
    center_longitude: float = None,
    search_location_name: str = None
) -> dict:
    """
    Search registered donors based on clinical compatibility, availability, and geographic proximity.
    
    Filters Applied:
    1. Account Status: User is active, role is DONOR, and profile is APPROVED/VERIFIED.
    2. Notification Consent: Donors must have consented to emergency notifications.
    3. Blood Compatibility: Matched using component-specific rules.
    4. Availability: Filtered by 'available' (only available) or 'all' (all consenting).
    5. Location & Distance: Filtered by max_distance_km if specified; no invented distances.
    6. Eligibility: Preliminary 56-day donation interval applied.
    """
    # 1. Base Query: Only active, role=DONOR, approved/verified donors
    query = db.session.query(User, DonorProfile).join(
        DonorProfile, User.id == DonorProfile.user_id
    ).filter(
        User.role == 'DONOR',
        User.is_active.is_(True),
        DonorProfile.verification_status.in_(['APPROVED', 'VERIFIED'])
    )

    # 2. Notification Consent (Consent to receive emergency requests)
    query = query.filter(DonorProfile.notification_consent.is_(True))

    # 3. Availability Filter
    if availability_filter == 'available':
        query = query.filter(DonorProfile.availability_status.is_(True))

    # 4. Blood Compatibility Filter
    comp_clean = (component_type or 'Whole Blood').strip()
    bg_clean = (blood_group or '').strip().upper() if blood_group else None

    compatible_groups = []
    if bg_clean and bg_clean in VALID_BLOOD_GROUPS:
        compatible_groups = get_compatible_donor_groups(bg_clean, comp_clean)
        if compatible_groups:
            query = query.filter(DonorProfile.declared_blood_group.in_(compatible_groups))
        else:
            # If compatibility cannot be determined reliably, return empty or flag for review
            query = query.filter(db.literal(False))
    elif bg_clean and bg_clean not in VALID_BLOOD_GROUPS and bg_clean != 'ALL':
        # Invalid blood group supplied
        query = query.filter(db.literal(False))

    # 5. Optional Search Query (Name or Donor Reference ID)
    if query_search:
        qs = query_search.strip()
        # Check if searching by reference ID format e.g. DON-0012 or #12 or 12
        numeric_id = None
        if qs.upper().startswith('DON-'):
            try:
                numeric_id = int(qs[4:])
            except ValueError:
                pass
        elif qs.startswith('#'):
            try:
                numeric_id = int(qs[1:])
            except ValueError:
                pass
        elif qs.isdigit():
            numeric_id = int(qs)

        if numeric_id:
            query = query.filter(db.or_(User.id == numeric_id, User.name.ilike(f"%{qs}%")))
        else:
            query = query.filter(User.name.ilike(f"%{qs}%"))

    # Execute candidate query to calculate distances and apply post-distance filtering
    candidates = query.all()

    # Determine center coordinates (custom center or hospital coordinates)
    if center_latitude is not None and center_longitude is not None:
        try:
            center_lat = float(center_latitude)
            center_lon = float(center_longitude)
            has_center_coords = True
        except (ValueError, TypeError):
            center_lat = hospital_org.latitude if hospital_org else None
            center_lon = hospital_org.longitude if hospital_org else None
            has_center_coords = center_lat is not None and center_lon is not None
    else:
        center_lat = hospital_org.latitude if hospital_org else None
        center_lon = hospital_org.longitude if hospital_org else None
        has_center_coords = center_lat is not None and center_lon is not None

    enriched_results = []
    for user, profile in candidates:
        donor_lat = profile.latitude
        donor_lon = profile.longitude
        has_donor_coords = donor_lat is not None and donor_lon is not None

        # Calculate distance from search center
        dist_km = None
        if has_center_coords and has_donor_coords:
            dist_km = haversine_distance(center_lat, center_lon, donor_lat, donor_lon)

        # Distance filtering:
        # If max_distance_km is requested (> 0):
        # Exclude candidates who have no coordinates or exceed the radius
        if max_distance_km is not None and max_distance_km > 0:
            if dist_km is None:
                # Location missing: exclude when distance filtering is explicitly requested
                continue
            if dist_km > max_distance_km:
                continue

        # Preliminary eligibility cooldown
        is_eligible, days_remaining = profile.is_eligible_to_donate(cooldown_days=56)

        # Compatibility categorization
        compatibility_status = "Exact Match"
        if bg_clean and profile.declared_blood_group != bg_clean:
            compatibility_status = "Compatible Group"

        # Display name formatting (Privacy-preserving or authorized clinical display)
        # Display name: First name + initial of last name or full clinical name
        parts = user.name.split()
        if len(parts) > 1:
            display_name = f"{parts[0]} {parts[-1][0]}."
        else:
            display_name = user.name

        donor_ref = f"DON-{user.id:04d}"

        # Verified donation count
        donation_count = user.donations.filter_by(verification_status='VERIFIED').count()

        enriched_results.append({
            'user': user,
            'profile': profile,
            'donor_id': user.id,
            'donor_reference': donor_ref,
            'display_name': display_name,
            'full_name': user.name,
            'blood_group': profile.declared_blood_group,
            'city': profile.city or 'Not Specified',
            'district': profile.district or '',
            'state': profile.state or '',
            'distance_km': dist_km,
            'distance_display': f"{dist_km:.1f} km" if dist_km is not None else "Location not specified",
            'is_available': profile.availability_status,
            'is_verified': profile.verification_status in ('APPROVED', 'VERIFIED'),
            'cooldown_eligible': is_eligible,
            'cooldown_days_remaining': days_remaining,
            'compatibility_status': compatibility_status,
            'donation_count': donation_count,
            'last_donation_date': profile.last_donation_date,
            'notification_consent': profile.notification_consent,
        })

    # Sort results:
    # 1. Exact match over compatible
    # 2. Available donors first
    # 3. Cooldown cleared first
    # 4. Nearest distance first (None placed at end)
    def sort_key(item):
        exact_rank = 0 if item['compatibility_status'] == "Exact Match" else 1
        avail_rank = 0 if item['is_available'] else 1
        cooldown_rank = 0 if item['cooldown_eligible'] else 1
        dist_rank = item['distance_km'] if item['distance_km'] is not None else 99999.0
        return (exact_rank, avail_rank, cooldown_rank, dist_rank)

    enriched_results.sort(key=sort_key)

    total_count = len(enriched_results)
    total_pages = math.ceil(total_count / per_page) if per_page > 0 else 1
    total_pages = max(1, total_pages)
    current_page = max(1, min(page, total_pages))

    start_idx = (current_page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_items = enriched_results[start_idx:end_idx]

    return {
        'items': paginated_items,
        'candidates': paginated_items,
        'donors': paginated_items,
        'total': total_count,
        'page': current_page,
        'per_page': per_page,
        'pages': total_pages,
        'has_prev': current_page > 1,
        'has_next': current_page < total_pages,
        'prev_num': current_page - 1 if current_page > 1 else None,
        'next_num': current_page + 1 if current_page < total_pages else None,
        'applied_filters': {
            'blood_group': bg_clean or '',
            'component_type': comp_clean,
            'max_distance_km': max_distance_km,
            'availability': availability_filter,
            'query': query_search or '',
            'center_lat': center_lat if has_center_coords else None,
            'center_lon': center_lon if has_center_coords else None,
            'location_name': search_location_name or '',
            'is_custom_location': center_latitude is not None and center_longitude is not None
        }
    }
