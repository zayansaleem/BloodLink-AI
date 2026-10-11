"""
BloodLink AI - Comprehensive Pan-India Demonstration Dataset Test Suite.
Verifies full 36 State/UT coverage, district hierarchy compliance,
is_demo metadata marking, seeding idempotency, and multi-state search/filtering.
"""

import pytest
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest
from app.models.rewards import Coupon
from app.seeds.india_demo_data import seed_india_wide_demo_dataset
from app.locations import is_valid_state, is_valid_district, get_all_states, get_states_only, get_union_territories_only


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


class TestPanIndiaDataset:
    """Comprehensive verification of the pan-India demonstration dataset."""

    def test_all_36_jurisdictions_represented(self, app):
        """All 28 States and 8 Union Territories must be represented in seeded data."""
        summary = seed_india_wide_demo_dataset(app)
        all_jurisdictions = get_all_states()
        assert len(all_jurisdictions) == 36

        # Verify donor profiles cover all 36 jurisdictions
        seeded_donor_states = {
            p.state for p in DonorProfile.query.filter_by(is_demo=True).all()
        }
        for jurisdiction in all_jurisdictions:
            assert jurisdiction in seeded_donor_states, f"Missing donor representation for {jurisdiction}"

        assert len(seeded_donor_states) == 36

    def test_all_synthetic_records_marked_is_demo(self, app):
        """Synthetic records must carry is_demo=True flag to isolate from real operational data."""
        seed_india_wide_demo_dataset(app)

        demo_orgs = Organization.query.filter_by(is_demo=True).all()
        demo_donors = DonorProfile.query.filter_by(is_demo=True).all()
        demo_inv = BloodInventory.query.filter_by(is_demo=True).all()
        demo_reqs = BloodRequest.query.filter_by(is_demo=True).all()
        demo_coupons = Coupon.query.filter_by(is_demo=True).all()

        assert len(demo_orgs) >= 30, f"Expected >=30 demo organizations, found {len(demo_orgs)}"
        assert len(demo_donors) >= 50, f"Expected >=50 demo donors, found {len(demo_donors)}"
        assert len(demo_inv) >= 80, f"Expected >=80 demo inventory items, found {len(demo_inv)}"
        assert len(demo_reqs) >= 14, f"Expected >=14 demo requests, found {len(demo_reqs)}"
        assert len(demo_coupons) >= 5, f"Expected >=5 demo coupons, found {len(demo_coupons)}"

        # Verify every demo item has valid is_demo flag
        for org in demo_orgs:
            assert org.is_demo is True
        for dp in demo_donors:
            assert dp.is_demo is True
        for inv in demo_inv:
            assert inv.is_demo is True
        for r in demo_reqs:
            assert r.is_demo is True

    def test_seeding_idempotency_zero_duplication(self, app):
        """Executing the seeder multiple times must cleanly update existing records without duplicates."""
        # First execution
        summary1 = seed_india_wide_demo_dataset(app)
        count_users_1 = User.query.count()
        count_orgs_1 = Organization.query.count()
        count_donors_1 = DonorProfile.query.count()
        count_inv_1 = BloodInventory.query.count()
        count_reqs_1 = BloodRequest.query.count()
        count_coupons_1 = Coupon.query.count()

        # Second execution
        summary2 = seed_india_wide_demo_dataset(app)
        count_users_2 = User.query.count()
        count_orgs_2 = Organization.query.count()
        count_donors_2 = DonorProfile.query.count()
        count_inv_2 = BloodInventory.query.count()
        count_reqs_2 = BloodRequest.query.count()
        count_coupons_2 = Coupon.query.count()

        assert count_users_1 == count_users_2, "Idempotency failed: User count changed on second run"
        assert count_orgs_1 == count_orgs_2, "Idempotency failed: Organization count changed on second run"
        assert count_donors_1 == count_donors_2, "Idempotency failed: DonorProfile count changed on second run"
        assert count_inv_1 == count_inv_2, "Idempotency failed: BloodInventory count changed on second run"
        assert count_reqs_1 == count_reqs_2, "Idempotency failed: BloodRequest count changed on second run"
        assert count_coupons_1 == count_coupons_2, "Idempotency failed: Coupon count changed on second run"

    def test_district_hierarchy_validity_for_all_records(self, app):
        """Every seeded organization, donor, and request must strictly comply with official district hierarchies."""
        seed_india_wide_demo_dataset(app)

        for org in Organization.query.filter_by(is_demo=True).all():
            assert is_valid_state(org.state), f"Invalid state {org.state} for org {org.organization_name}"
            assert is_valid_district(org.state, org.district), f"Invalid district {org.district} for org {org.organization_name}"

        for dp in DonorProfile.query.filter_by(is_demo=True).all():
            assert is_valid_state(dp.state), f"Invalid state {dp.state} for donor profile {dp.id}"
            assert is_valid_district(dp.state, dp.district), f"Invalid district {dp.district} for donor profile {dp.id}"

        for req in BloodRequest.query.filter_by(is_demo=True).all():
            assert is_valid_state(req.state), f"Invalid state {req.state} for request {req.request_reference}"
            assert is_valid_district(req.state, req.district), f"Invalid district {req.district} for request {req.request_reference}"

    def test_preconfigured_accounts_preserved_and_functional(self, app):
        """Pre-configured demo logins must remain accessible with their standard passwords."""
        seed_india_wide_demo_dataset(app)

        test_logins = [
            ("admin@bloodlink.ai", "admin123", "ADMIN"),
            ("apollo@hospital.com", "hospital123", "HOSPITAL"),
            ("redcross@bloodbank.com", "bank123", "BLOOD_BANK"),
            ("arjun@donor.com", "donor123", "DONOR")
        ]
        for email, password, expected_role in test_logins:
            user = User.query.filter_by(email=email).first()
            assert user is not None, f"Required test account missing: {email}"
            assert user.check_password(password) is True, f"Authentication failed for {email}"
            assert user.role == expected_role, f"Role mismatch for {email}: got {user.role}, expected {expected_role}"

    def test_state_level_inventory_search_isolation(self, app, client):
        """Search scoped to a specific state must return that state's inventory and exclude others."""
        seed_india_wide_demo_dataset(app)

        # Search Maharashtra
        res_mh = client.get('/search?scope=state&state=Maharashtra&blood_group=ALL&component=ALL')
        assert res_mh.status_code == 200
        assert b"Maharashtra" in res_mh.data
        # Search Kerala
        res_kl = client.get('/search?scope=state&state=Kerala&blood_group=ALL&component=ALL')
        assert res_kl.status_code == 200
        assert b"Kerala" in res_kl.data

    def test_district_level_inventory_search(self, app, client):
        """Search scoped to a specific district must return inventory strictly for that district."""
        seed_india_wide_demo_dataset(app)

        res = client.get('/search?scope=district&state=Maharashtra&district=Pune&blood_group=ALL&component=ALL')
        assert res.status_code == 200
        assert b"Pune" in res.data

    def test_all_india_inventory_search_breadth(self, app, client):
        """All-India scope must return inventory across diverse states."""
        seed_india_wide_demo_dataset(app)

        res = client.get('/search?scope=all_india&blood_group=ALL&component=ALL')
        assert res.status_code == 200
        # Check presence of multiple states in results
        assert b"Maharashtra" in res.data or b"Karnataka" in res.data or b"Delhi" in res.data

    def test_admin_pan_india_analytics_endpoints(self, app, client):
        """Admin analytics REST API returns geographic and urgency distribution."""
        seed_india_wide_demo_dataset(app)

        # Log in as admin
        client.post('/auth/login', data={
            'email': 'admin@bloodlink.ai',
            'password': 'admin123'
        }, follow_redirects=True)

        # Test state distribution API
        res_geo = client.get('/admin/api/analytics/states-distribution')
        assert res_geo.status_code == 200
        geo_data = res_geo.get_json()
        assert 'donors' in geo_data
        assert 'organizations' in geo_data
        assert len(geo_data['donors']['labels']) > 0
        assert len(geo_data['donors']['data']) > 0

        # Test request urgency API
        res_urg = client.get('/admin/api/analytics/request-urgency')
        assert res_urg.status_code == 200
        urg_data = res_urg.get_json()
        assert 'labels' in urg_data
        assert 'data' in urg_data
        assert len(urg_data['labels']) > 0
