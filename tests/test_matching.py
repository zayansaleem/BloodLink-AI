import pytest
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization
from app.models.request import BloodRequest, DonorMatch
from app.matching.compatibility import (
    is_preliminarily_compatible,
    get_compatible_donor_groups
)
from app.matching.engine import (
    haversine_distance,
    calculate_donor_match_score,
    run_donor_matching
)


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


class TestComponentCompatibility:
    """Tests for preliminary clinical compatibility across blood components."""

    def test_whole_blood_and_rbc_compatibility(self):
        # O- is universal RBC donor
        all_groups = ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+']
        for g in all_groups:
            assert is_preliminarily_compatible('O-', g, 'Whole Blood') is True
            assert is_preliminarily_compatible('O-', g, 'Red Blood Cells') is True

        # AB+ is universal recipient for RBC
        for g in all_groups:
            assert is_preliminarily_compatible(g, 'AB+', 'Red Blood Cells') is True

        # Incompatible matches
        assert is_preliminarily_compatible('A+', 'B+', 'Whole Blood') is False
        assert is_preliminarily_compatible('B+', 'A+', 'Whole Blood') is False
        assert is_preliminarily_compatible('AB+', 'O-', 'Whole Blood') is False

    def test_plasma_compatibility_reversed(self):
        # In plasma transfusions, AB is universal donor, O is universal recipient
        assert is_preliminarily_compatible('AB+', 'O+', 'Plasma') is True
        assert is_preliminarily_compatible('AB-', 'A+', 'Plasma') is True
        # O- cannot donate plasma to A+
        assert is_preliminarily_compatible('O-', 'A+', 'Plasma') is False


class TestHaversineDistance:
    """Tests for geographic distance projections."""

    def test_same_point(self):
        assert haversine_distance(12.9716, 77.5946, 12.9716, 77.5946) == 0.0

    def test_known_approximate_distance(self):
        # Bengaluru to Mysuru ~ 130 km
        dist = haversine_distance(12.9716, 77.5946, 12.2958, 76.6394)
        assert 120.0 <= dist <= 150.0

    def test_none_coordinate_handling(self):
        assert haversine_distance(None, 77.59, 12.97, 77.59) == 999.0


class TestSmartDonorMatching:
    """Tests for smart donor matching and ranking."""

    def test_matching_excludes_incompatible_or_unavailable(self, app):
        donor1 = User(name="Donor One", email="d1@test.com", role="DONOR")
        donor1.set_password("pass")
        db.session.add(donor1)
        db.session.flush()

        profile1 = DonorProfile(
            user_id=donor1.id, declared_blood_group="O+",
            city="Bengaluru", latitude=12.9716, longitude=77.5946,
            availability_status=False, notification_consent=True
        )
        db.session.add(profile1)

        req = BloodRequest(
            request_reference="REQ-TEST-1", requesting_organization_id=1,
            blood_group="O+", component_type="Whole Blood", units_required=1,
            location="Test Hospital", latitude=12.9716, longitude=77.5946,
            urgency_level="HIGH", verification_status="VERIFIED", request_status="VERIFIED",
            contact_phone="123"
        )
        db.session.add(req)
        db.session.commit()

        score, breakdown = calculate_donor_match_score(donor1, req)
        assert score == 0.0
        assert "unavailable" in breakdown['reason'].lower()

    def test_duplicate_matches_prevented(self, app):
        donor = User(name="Eligible Donor", email="d2@test.com", role="DONOR")
        donor.set_password("pass")
        db.session.add(donor)
        db.session.flush()

        profile = DonorProfile(
            user_id=donor.id, declared_blood_group="O-",
            city="Bengaluru", latitude=12.9716, longitude=77.5946,
            availability_status=True, notification_consent=True
        )
        db.session.add(profile)

        req = BloodRequest(
            request_reference="REQ-TEST-2", requesting_organization_id=1,
            blood_group="O+", component_type="Whole Blood", units_required=1,
            location="Test Hospital", latitude=12.9716, longitude=77.5946,
            urgency_level="HIGH", verification_status="VERIFIED", request_status="VERIFIED",
            contact_phone="123"
        )
        db.session.add(req)
        db.session.commit()

        matches_pass1 = run_donor_matching(req, notify_donors=False)
        assert len(matches_pass1) == 1

        # Second execution must not duplicate records
        matches_pass2 = run_donor_matching(req, notify_donors=False)
        assert len(matches_pass2) == 1
        assert DonorMatch.query.filter_by(request_id=req.id).count() == 1
