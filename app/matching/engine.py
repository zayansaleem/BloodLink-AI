import math
import json
from datetime import datetime, timezone
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.request import BloodRequest, DonorMatch
from app.matching.compatibility import is_preliminarily_compatible
from app.notifications.services import create_notification
from config import Config


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two decimal-degree coordinate points."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 999.0

    r = 6371.0  # Earth's radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(r * c, 2)


def calculate_donor_match_score(donor_user: User, blood_request: BloodRequest) -> tuple[float, dict]:
    """
    Computes preliminary coordination match score (0-100).
    NOTE: Coordination score, NOT a medical suitability or cross-match score.
    """
    profile = donor_user.donor_profile
    if not profile:
        return 0.0, {'reason': 'No donor profile found'}

    # 1. Compatibility check
    if not is_preliminarily_compatible(profile.declared_blood_group, blood_request.blood_group, blood_request.component_type):
        return 0.0, {'reason': 'Preliminary ABO/Component incompatible'}

    # 2. Exclude unavailable or restricted donors
    is_eligible, cooldown_days = profile.is_eligible_to_donate()
    if not profile.availability_status:
        return 0.0, {'reason': 'Donor has marked status as unavailable'}
    if not is_eligible:
        return 0.0, {
            'reason': f'Donor restricted by clinical recovery/cooldown policy ({cooldown_days} days remaining)',
            'cooldown_days_remaining': cooldown_days
        }

    # 3. Notification Consent
    if not profile.notification_consent:
        return 0.0, {'reason': 'Donor has opted out of notifications'}

    # A. Proximity Score (35%)
    has_coords = (
        profile.latitude is not None and profile.longitude is not None and
        blood_request.latitude is not None and blood_request.longitude is not None
    )

    max_distance_limit = getattr(Config, 'MAX_MATCH_DISTANCE_KM', 75.0)

    if has_coords:
        dist_km = haversine_distance(profile.latitude, profile.longitude, blood_request.latitude, blood_request.longitude)
        if dist_km > max_distance_limit:
            return 0.0, {
                'reason': f"Donor distance ({dist_km} km) exceeds maximum matching radius ({max_distance_limit} km)",
                'distance_km': dist_km
            }
        elif dist_km <= 5.0:
            proximity_score = 100.0
        elif dist_km <= 15.0:
            proximity_score = 90.0 - ((dist_km - 5.0) * 1.5)
        elif dist_km <= 50.0:
            proximity_score = max(15.0, 75.0 - ((dist_km - 15.0) * 1.6))
        else:
            proximity_score = max(5.0, 15.0 - ((dist_km - 50.0) * 0.4))
    else:
        # Coarse location matching using State & District when coordinates are unavailable
        donor_state = (profile.state or '').strip().lower()
        req_state = (blood_request.state or '').strip().lower()
        donor_dist = (profile.district or '').strip().lower()
        req_dist = (blood_request.district or '').strip().lower()

        if donor_state and req_state and donor_state == req_state:
            if donor_dist and req_dist and donor_dist == req_dist:
                proximity_score = 85.0
                dist_km = 10.0  # Coarse district approximation
            else:
                proximity_score = 50.0
                dist_km = 60.0  # Coarse state approximation
        else:
            # Different states without coordinates cannot be matched for urgent local dispatch
            return 0.0, {
                'reason': f"Donor state ({profile.state}) does not match request state ({blood_request.state})",
                'distance_km': 999.0
            }

    # B. Availability / Cooldown (30%)
    availability_score = 100.0 if is_eligible else 15.0

    # C. Profile Confirmation / Experience (20%)
    # Verified donors with past successful donations earn reliability weight
    past_donations = donor_user.donations.filter_by(verification_status='VERIFIED').count()
    recency_score = min(100.0, 50.0 + (past_donations * 15.0))

    # D. Suitability (15%) - Exact blood group match bonus
    is_exact = (profile.declared_blood_group == blood_request.blood_group)
    suitability_score = 100.0 if is_exact else 80.0

    composite_score = (
        (0.35 * proximity_score) +
        (0.30 * availability_score) +
        (0.20 * recency_score) +
        (0.15 * suitability_score)
    )

    if not is_eligible:
        composite_score *= 0.4  # Penalize if currently in active cooldown

    composite_score = round(min(100.0, max(0.0, composite_score)), 1)

    breakdown = {
        'proximity_score': round(proximity_score, 1),
        'distance_km': dist_km,
        'availability_score': availability_score,
        'is_eligible': is_eligible,
        'cooldown_days_left': cooldown_days,
        'recency_score': round(recency_score, 1),
        'suitability_score': suitability_score,
        'is_exact_match': is_exact,
        'total_score': composite_score
    }

    return composite_score, breakdown


def run_donor_matching(blood_request: BloodRequest, notify_donors: bool = True, max_candidates: int = 10) -> list[DonorMatch]:
    """
    Executes preliminary matching for a verified active blood request.
    Stores DonorMatch candidates and dispatches authorized notifications.
    """
    if not blood_request.is_active or blood_request.verification_status != 'VERIFIED':
        return []

    # Query all active donors with consent
    donors = User.query.filter_by(role='DONOR', is_active=True).all()
    candidate_matches = []

    for donor in donors:
        score, breakdown = calculate_donor_match_score(donor, blood_request)
        if score > 0:
            candidate_matches.append({
                'donor': donor,
                'score': score,
                'distance': breakdown.get('distance_km', 999.0),
                'breakdown': breakdown
            })

    # Sort descending by score, ascending by distance
    candidate_matches.sort(key=lambda x: (-x['score'], x['distance']))
    top_candidates = candidate_matches[:max_candidates]

    saved_matches = []
    for cand in top_candidates:
        donor = cand['donor']
        # Prevent duplicate matches
        existing = DonorMatch.query.filter_by(
            request_id=blood_request.id,
            donor_id=donor.id
        ).first()

        if not existing:
            match_record = DonorMatch(
                request_id=blood_request.id,
                donor_id=donor.id,
                approximate_distance=cand['distance'],
                match_score=cand['score'],
                match_status='PRELIMINARY',
                score_breakdown=json.dumps(cand['breakdown']),
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(match_record)
            saved_matches.append(match_record)

        # Ensure persistent DonorInvitation exists for this eligible donor
        from app.models.communication import DonorInvitation
        existing_inv = DonorInvitation.query.filter_by(
            donor_id=donor.id,
            blood_request_id=blood_request.id
        ).first()

        if not existing_inv:
            inv = DonorInvitation(
                donor_id=donor.id,
                hospital_id=blood_request.requesting_organization_id,
                blood_request_id=blood_request.id,
                invitation_status='SENT',
                message=(
                    f"Emergency requirement for {blood_request.units_required} unit(s) of "
                    f"{blood_request.blood_group} ({blood_request.component_type}) at {blood_request.location}."
                ),
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(inv)

        # Optional notification dispatch
        if notify_donors and not existing:
            match_record.match_status = 'NOTIFIED'
            create_notification(
                recipient_id=donor.id,
                notification_type='DONOR_MATCH',
                title=f"Urgent Need: {blood_request.blood_group} ({blood_request.urgency_level})",
                message=(
                    f"An urgent verified request for {blood_request.blood_group} ({blood_request.component_type}) "
                    f"has been opened at {blood_request.location}. Approximate distance: {cand['distance']} km."
                )
            )

    if saved_matches:
        # Update request status to MATCHING if still in VERIFIED
        if blood_request.request_status == 'VERIFIED':
            blood_request.request_status = 'MATCHING'
        db.session.commit()

    return DonorMatch.query.filter_by(request_id=blood_request.id).order_by(DonorMatch.match_score.desc()).all()


def find_suitable_blood_banks(blood_request: BloodRequest, max_distance_km: float = None) -> dict:
    """
    Identifies verified blood banks matching an active emergency request by
    compatible component inventory, quantity, and geographic proximity.
    """
    from app.models.organization import Organization
    from app.models.inventory import BloodInventory
    from app.matching.compatibility import get_compatible_donor_groups

    if not blood_request.is_active or blood_request.verification_status != 'VERIFIED':
        return {
            'suitable_banks': [],
            'banks_with_stock_count': 0,
            'total_compatible_units': 0,
            'regional_banks_count': 0
        }

    # Query all verified blood banks (excluding requesting facility)
    banks = Organization.query.filter(
        Organization.organization_type == 'BLOOD_BANK',
        Organization.verification_status.in_(['VERIFIED', 'APPROVED']),
        Organization.id != blood_request.requesting_organization_id
    ).all()

    # Determine compatible donor groups
    comp_type = blood_request.component_type or 'Whole Blood'
    compatible_groups = get_compatible_donor_groups(blood_request.blood_group, comp_type)
    if not compatible_groups:
        compatible_groups = [blood_request.blood_group]

    max_dist = max_distance_km if max_distance_km is not None else getattr(Config, 'MAX_MATCH_DISTANCE_KM', 100.0)

    evaluated_banks = []
    total_compatible_units = 0
    banks_with_stock = 0

    for bank in banks:
        # Distance calculation
        dist_km = None
        has_coords = (
            bank.latitude is not None and bank.longitude is not None and
            blood_request.latitude is not None and blood_request.longitude is not None
        )
        if has_coords:
            dist_km = haversine_distance(bank.latitude, bank.longitude, blood_request.latitude, blood_request.longitude)
        else:
            # Fallback distance approximation
            if bank.state and blood_request.state and bank.state.strip().lower() == blood_request.state.strip().lower():
                if bank.district and blood_request.district and bank.district.strip().lower() == blood_request.district.strip().lower():
                    dist_km = 15.0
                else:
                    dist_km = 60.0
            else:
                dist_km = 999.0

        # Query available unreserved units for compatible blood groups & component
        inventories = BloodInventory.query.filter(
            BloodInventory.blood_bank_id == bank.id,
            BloodInventory.component_type == comp_type,
            BloodInventory.blood_group.in_(compatible_groups)
        ).all()

        available_stock = sum(max(0, inv.available_units - getattr(inv, 'reserved_units', 0)) for inv in inventories)
        if available_stock > 0:
            total_compatible_units += available_stock
            banks_with_stock += 1

        is_in_range = (dist_km is not None and dist_km <= max_dist) or (dist_km is None)

        if available_stock >= blood_request.units_required:
            stock_status = 'SUFFICIENT_STOCK'
        elif available_stock > 0:
            stock_status = 'PARTIAL_STOCK'
        else:
            stock_status = 'NO_STOCK'

        evaluated_banks.append({
            'bank': bank,
            'available_stock': available_stock,
            'distance_km': dist_km,
            'is_in_range': is_in_range,
            'stock_status': stock_status,
            'has_stock': available_stock > 0
        })

    # Sort:
    # 1. Banks with sufficient stock first, then partial stock, then no stock
    # 2. Within stock tier, sort by distance
    def bank_sort_key(b):
        stock_rank = 0 if b['stock_status'] == 'SUFFICIENT_STOCK' else (1 if b['stock_status'] == 'PARTIAL_STOCK' else 2)
        dist_rank = b['distance_km'] if b['distance_km'] is not None else 9999.0
        return (stock_rank, dist_rank)

    evaluated_banks.sort(key=bank_sort_key)

    return {
        'suitable_banks': evaluated_banks,
        'banks_with_stock_count': banks_with_stock,
        'total_compatible_units': total_compatible_units,
        'regional_banks_count': len([b for b in evaluated_banks if b['is_in_range']])
    }
