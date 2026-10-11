import json
from datetime import datetime, timezone
from config import Config
from app.models.inventory import BloodInventory
from app.models.organization import Organization
from app.extensions import db


def calculate_emergency_priority(blood_request) -> tuple[float, dict]:
    """
    Explainable Emergency Prioritization Engine (Server-side).
    
    Inputs evaluated:
    - Urgency category (verified)
    - Time sensitivity / clinical deadline
    - Reported regional inventory shortage
    - Request waiting time / age
    
    Returns: (final_score: float, breakdown: dict)
    """
    # 1. Reject inactive requests
    if not blood_request.is_active:
        return 0.0, {
            'status': 'INACTIVE',
            'reason': f"Request is in inactive state: {blood_request.request_status}",
            'total_score': 0.0
        }

    # 2. Check verification status
    is_verified = (blood_request.verification_status == 'VERIFIED')
    if not is_verified:
        # Unverified requests are non-trusted; assign baseline review score
        return 20.0, {
            'status': 'UNVERIFIED',
            'reason': "Request has not yet been verified by clinical coordinators.",
            'total_score': 20.0
        }

    weights = getattr(Config, 'PRIORITY_WEIGHTS', {
        'urgency': 40.0,
        'time_sensitivity': 30.0,
        'inventory_shortage': 20.0,
        'waiting_time': 10.0
    })

    # A. Urgency Factor (Max 40 pts)
    urgency_map = {
        'CRITICAL': 40.0,
        'HIGH': 28.0,
        'MEDIUM': 16.0,
        'ROUTINE': 8.0
    }
    urgency_score = urgency_map.get(blood_request.urgency_level.upper(), 15.0)

    # B. Time Sensitivity / Deadline Proximity (Max 30 pts)
    deadline_score = 0.0
    if blood_request.clinical_deadline:
        deadline = blood_request.clinical_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        
        hours_to_deadline = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600.0
        if hours_to_deadline <= 2.0:
            deadline_score = 30.0
        elif hours_to_deadline <= 6.0:
            deadline_score = 22.0
        elif hours_to_deadline <= 12.0:
            deadline_score = 15.0
        elif hours_to_deadline <= 24.0:
            deadline_score = 8.0
        else:
            deadline_score = 4.0
    else:
        # Default based on urgency level if no clinical deadline is specified
        if blood_request.urgency_level == 'CRITICAL':
            deadline_score = 20.0
        elif blood_request.urgency_level == 'HIGH':
            deadline_score = 12.0
        else:
            deadline_score = 5.0

    # C. Reported Inventory Shortage Factor (Max 20 pts)
    # Filter on verified blood banks; prioritize regional/state inventory deficit
    base_inv_query = db.session.query(db.func.coalesce(db.func.sum(BloodInventory.available_units), 0))\
        .join(Organization, BloodInventory.blood_bank_id == Organization.id)\
        .filter(
            Organization.verification_status == 'VERIFIED',
            BloodInventory.blood_group == blood_request.blood_group,
            BloodInventory.component_type == blood_request.component_type
        )

    # If state is specified, check regional state stock first
    regional_stock = None
    if blood_request.state:
        regional_stock = base_inv_query.filter(Organization.state.ilike(f"%{blood_request.state.strip()}%")).scalar()

    total_reported_stock = regional_stock if (regional_stock is not None and regional_stock > 0) else (base_inv_query.scalar() or 0)

    if total_reported_stock == 0:
        inventory_score = 20.0  # Zero regional inventory available!
    elif total_reported_stock < blood_request.units_required:
        inventory_score = 16.0  # Severe regional deficit
    elif total_reported_stock < (blood_request.units_required * 2):
        inventory_score = 10.0  # Marginal reserve
    else:
        inventory_score = 3.0   # Adequate reserve

    # D. Waiting Time / Anti-Starvation (Max 10 pts)
    # Increases by 1.0 point per hour elapsed, capped at 10.0
    elapsed_hours = blood_request.hours_elapsed()
    waiting_score = min(10.0, round(elapsed_hours * 1.0, 1))

    # Composite sum (clamped 0 to 100)
    total_score = round(min(100.0, max(5.0, urgency_score + deadline_score + inventory_score + waiting_score)), 1)

    breakdown = {
        'urgency_score': urgency_score,
        'urgency_level': blood_request.urgency_level,
        'deadline_score': deadline_score,
        'has_clinical_deadline': blood_request.clinical_deadline is not None,
        'inventory_score': inventory_score,
        'reported_inventory_units': total_reported_stock,
        'waiting_score': waiting_score,
        'elapsed_hours': round(elapsed_hours, 1),
        'total_score': total_score,
        'calculated_at': datetime.now(timezone.utc).isoformat()
    }

    return total_score, breakdown


def update_request_priority(blood_request) -> float:
    """Recalculate and persist the priority score and JSON breakdown."""
    score, breakdown = calculate_emergency_priority(blood_request)
    blood_request.priority_score = score
    blood_request.priority_breakdown = json.dumps(breakdown)
    return score
