import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models.request import BloodRequest
from app.models.inventory import BloodInventory
from app.matching.prioritization import calculate_emergency_priority, update_request_priority


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


class TestEmergencyPrioritization:
    """Tests for the explainable Emergency Request Prioritization Engine."""

    def test_inactive_request_rejected(self, app):
        req = BloodRequest(
            request_reference="REQ-INACT-1", requesting_organization_id=1,
            blood_group="O+", component_type="Whole Blood", units_required=1,
            location="Test Clinic", urgency_level="CRITICAL",
            verification_status="VERIFIED", request_status="CANCELLED",
            contact_phone="123"
        )
        score, breakdown = calculate_emergency_priority(req)
        assert score == 0.0
        assert breakdown['status'] == 'INACTIVE'

    def test_unverified_request_assigned_baseline(self, app):
        req = BloodRequest(
            request_reference="REQ-UNVER-1", requesting_organization_id=1,
            blood_group="O+", component_type="Whole Blood", units_required=1,
            location="Test Clinic", urgency_level="CRITICAL",
            verification_status="PENDING", request_status="SUBMITTED",
            contact_phone="123"
        )
        score, breakdown = calculate_emergency_priority(req)
        assert score == 20.0
        assert breakdown['status'] == 'UNVERIFIED'

    def test_urgency_hierarchy_for_verified_requests(self, app):
        req_crit = BloodRequest(
            request_reference="REQ-CRIT", requesting_organization_id=1,
            blood_group="O+", component_type="Whole Blood", units_required=1,
            location="Test", urgency_level="CRITICAL",
            verification_status="VERIFIED", request_status="VERIFIED",
            contact_phone="123"
        )
        req_high = BloodRequest(
            request_reference="REQ-HIGH", requesting_organization_id=1,
            blood_group="O+", component_type="Whole Blood", units_required=1,
            location="Test", urgency_level="HIGH",
            verification_status="VERIFIED", request_status="VERIFIED",
            contact_phone="123"
        )
        score_crit, _ = calculate_emergency_priority(req_crit)
        score_high, _ = calculate_emergency_priority(req_high)

        assert score_crit > score_high

    def test_deadline_proximity_boost(self, app):
        # Imminent deadline (2 hours away) vs distant deadline (24 hours away)
        req_imminent = BloodRequest(
            request_reference="REQ-IMM", requesting_organization_id=1,
            blood_group="O+", component_type="Whole Blood", units_required=1,
            location="Test", urgency_level="HIGH",
            clinical_deadline=datetime.now(timezone.utc) + timedelta(hours=1.5),
            verification_status="VERIFIED", request_status="VERIFIED",
            contact_phone="123"
        )
        req_distant = BloodRequest(
            request_reference="REQ-DIST", requesting_organization_id=1,
            blood_group="O+", component_type="Whole Blood", units_required=1,
            location="Test", urgency_level="HIGH",
            clinical_deadline=datetime.now(timezone.utc) + timedelta(hours=23),
            verification_status="VERIFIED", request_status="VERIFIED",
            contact_phone="123"
        )
        score_imm, _ = calculate_emergency_priority(req_imminent)
        score_dist, _ = calculate_emergency_priority(req_distant)

        assert score_imm > score_dist
