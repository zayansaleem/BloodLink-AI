"""
BloodLink AI - Regression Test Suite for Engineering Audit Fixes.
Verifies:
1. Thrissur blood search returns verified inventory.
2. Blood search handles blood_group='ALL' and component='ALL' aliases correctly.
3. Empty district searches display informative context and state-level fallback.
4. Maximum matching distance (75 km) is strictly enforced in donor matching.
5. Cross-state coarse matching without coordinates is rejected.
6. Clinical staff are blocked from self-verifying personal blood donations.
7. Reward transactions enforce unique donation constraints against duplicates.
8. Emergency prioritization scarcity calculations ignore unverified blood bank inventory.
"""

import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest
from app.models.donation import Donation
from app.models.rewards import RewardTransaction
from app.seeds.india_demo_data import seed_india_wide_demo_dataset
from app.matching.engine import calculate_donor_match_score
from app.matching.prioritization import calculate_emergency_priority
from app.rewards.services import award_donation_points


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


class TestEngineeringAuditFixes:
    """Rigorous regression tests for all verified defects and architectural fixes."""

    def test_thrissur_blood_search_returns_inventory(self, app, client):
        """Selecting Kerala -> Thrissur -> O+ must return matching inventory."""
        seed_india_wide_demo_dataset(app)

        res = client.get('/search?scope=district&state=Kerala&district=Thrissur&blood_group=O%2B')
        assert res.status_code == 200
        assert b"Government Medical College Blood Centre Thrissur" in res.data
        assert b"O+" in res.data
        assert b"Units" in res.data

    def test_district_level_search_isolation(self, app, client):
        """Searching Thrissur must exclude blood banks in other districts like Ernakulam."""
        seed_india_wide_demo_dataset(app)

        res = client.get('/search?scope=district&state=Kerala&district=Thrissur&blood_group=ALL')
        assert res.status_code == 200
        assert b"Government Medical College Blood Centre Thrissur" in res.data
        # Must not leak Ernakulam or TVM banks into Thrissur district results
        assert b"IMA Voluntary Blood Bank Kochi" not in res.data
        assert b"Sree Chitra Tirunal Blood Center" not in res.data

    def test_search_all_group_query_parameter(self, app, client):
        """Queries with blood_group='ALL' or component='ALL' must return results without error."""
        seed_india_wide_demo_dataset(app)

        res = client.get('/search?scope=state&state=Kerala&blood_group=ALL&component=ALL')
        assert res.status_code == 200
        assert b"Government Medical College Blood Centre Thrissur" in res.data
        assert b"IMA Voluntary Blood Bank Kochi" in res.data

    def test_empty_district_shows_contextual_state_fallback(self, app, client):
        """Searching a district without collection centers shows contextual state fallback."""
        seed_india_wide_demo_dataset(app)

        res = client.get('/search?scope=district&state=Kerala&district=Kollam&blood_group=O%2B')
        assert res.status_code == 200
        assert b"No matching blood inventory found" in res.data
        assert b"Kollam, Kerala" in res.data
        assert b"Expand to Entire Kerala" in res.data

    def test_max_distance_donor_matching_enforced(self, app):
        """Donors beyond MAX_MATCH_DISTANCE_KM (75 km) must receive a 0.0 match score."""
        # Hospital in Thrissur
        req = BloodRequest(
            request_reference='REQ-AUDIT-01', requesting_organization_id=1,
            blood_group='O+', component_type='Whole Blood', units_required=2,
            location='GMC Thrissur', state='Kerala', district='Thrissur', city='Thrissur',
            latitude=10.6200, longitude=76.2050,
            urgency_level='CRITICAL', verification_status='VERIFIED', request_status='VERIFIED',
            contact_phone='1234567890'
        )
        db.session.add(req)

        # Donor 1: In Ernakulam / Kochi (~72 km away, within 75 km)
        u1 = User(name='Near Donor', email='near@test.com', role='DONOR')
        u1.set_password('pass')
        db.session.add(u1)
        db.session.flush()
        p1 = DonorProfile(
            user_id=u1.id, declared_blood_group='O+',
            state='Kerala', district='Ernakulam', city='Kochi',
            latitude=9.9816, longitude=76.2999,
            availability_status=True, notification_consent=True
        )
        db.session.add(p1)

        # Donor 2: In Bengaluru (~350 km away, well beyond 75 km)
        u2 = User(name='Far Donor', email='far@test.com', role='DONOR')
        u2.set_password('pass')
        db.session.add(u2)
        db.session.flush()
        p2 = DonorProfile(
            user_id=u2.id, declared_blood_group='O+',
            state='Karnataka', district='Bengaluru Urban', city='Bengaluru',
            latitude=12.9716, longitude=77.5946,
            availability_status=True, notification_consent=True
        )
        db.session.add(p2)
        db.session.commit()

        score_near, bd_near = calculate_donor_match_score(u1, req)
        score_far, bd_far = calculate_donor_match_score(u2, req)

        assert score_near > 50.0
        assert bd_near.get('distance_km') <= 75.0
        assert score_far == 0.0
        assert "exceeds maximum matching radius" in bd_far.get('reason')

    def test_coarse_matching_cross_state_rejected(self, app):
        """When coordinates are missing, donors in different states must be excluded."""
        req = BloodRequest(
            request_reference='REQ-COARSE-KL', requesting_organization_id=1,
            blood_group='O+', component_type='Whole Blood', units_required=1,
            location='Hospital Ward', state='Kerala', district='Thrissur', city='Thrissur',
            latitude=None, longitude=None,
            urgency_level='HIGH', verification_status='VERIFIED', request_status='VERIFIED',
            contact_phone='1234567890'
        )
        db.session.add(req)

        # Donor without coords in Punjab
        u_punjab = User(name='Punjab Donor', email='punjab@test.com', role='DONOR')
        u_punjab.set_password('pass')
        db.session.add(u_punjab)
        db.session.flush()
        p_punjab = DonorProfile(
            user_id=u_punjab.id, declared_blood_group='O+',
            state='Punjab', district='Ludhiana', city='Ludhiana',
            latitude=None, longitude=None,
            availability_status=True, notification_consent=True
        )
        db.session.add(p_punjab)
        db.session.commit()

        score, bd = calculate_donor_match_score(u_punjab, req)
        assert score == 0.0
        assert "does not match request state" in bd.get('reason')

    def test_staff_cannot_verify_own_donation(self, app, client):
        """Clinical blood bank staff must be blocked from self-verifying personal donations."""
        bank = Organization(
            organization_name='City Blood Center', organization_type='BLOOD_BANK',
            address='Station Rd', contact_phone='12345', verification_status='VERIFIED'
        )
        db.session.add(bank)
        db.session.flush()

        staff_user = User(name='Staff Member', email='staff@cityblood.org', role='BLOOD_BANK')
        staff_user.set_password('securepass')
        db.session.add(staff_user)
        db.session.flush()

        db.session.add(OrganizationMembership(organization_id=bank.id, user_id=staff_user.id, membership_role='ADMIN'))
        db.session.commit()

        # Staff records personal donation
        donation = Donation(
            donor_id=staff_user.id, blood_bank_id=bank.id, units=1,
            verification_status='PENDING'
        )
        db.session.add(donation)
        db.session.commit()

        # Login as staff
        client.post('/auth/login', data={'email': 'staff@cityblood.org', 'password': 'securepass'})

        # Attempt self-verification
        res = client.post(f'/blood-bank/donations/{donation.id}/verify', follow_redirects=True)
        assert res.status_code == 200
        assert b"cannot verify their own personal blood donation" in res.data

        # Status must remain PENDING
        db.session.refresh(donation)
        assert donation.verification_status == 'PENDING'

    def test_reward_transaction_unique_donation_constraint(self, app):
        """Reward transactions must reject duplicate credits for the same donation."""
        donor = User(name='Donor Hero', email='hero@test.com', role='DONOR')
        donor.set_password('pass')
        bank = Organization(organization_name='Bank', organization_type='BLOOD_BANK', address='A', contact_phone='1', verification_status='VERIFIED')
        db.session.add_all([donor, bank])
        db.session.commit()

        don = Donation(donor_id=donor.id, blood_bank_id=bank.id, units=1, verification_status='VERIFIED')
        db.session.add(don)
        db.session.commit()

        # First issuance succeeds
        assert award_donation_points(don.id, 100) is True
        assert donor.reward_balance == 100

        # Second issuance fails safely
        assert award_donation_points(don.id, 100) is False
        assert donor.reward_balance == 100

    def test_priority_scarcity_only_counts_verified_inventory(self, app):
        """Unverified blood banks must not skew emergency prioritization scarcity calculations."""
        # Unverified blood bank has 50 units
        unverified_bank = Organization(
            organization_name='Bogus Blood Bank', organization_type='BLOOD_BANK',
            address='Unknown', contact_phone='000', verification_status='PENDING'
        )
        db.session.add(unverified_bank)
        db.session.flush()

        inv = BloodInventory(
            blood_bank_id=unverified_bank.id, blood_group='AB-', component_type='Red Blood Cells',
            available_units=50
        )
        db.session.add(inv)
        db.session.commit()

        # Request for AB- RBC at a verified clinic
        req = BloodRequest(
            request_reference='REQ-SCARCITY-01', requesting_organization_id=1,
            blood_group='AB-', component_type='Red Blood Cells', units_required=2,
            location='Trauma Ward', urgency_level='HIGH',
            verification_status='VERIFIED', request_status='VERIFIED',
            contact_phone='123'
        )
        db.session.add(req)
        db.session.commit()

        score, breakdown = calculate_emergency_priority(req)
        # Because unverified stock is ignored, reported inventory should be 0 and scarcity score should be max (20.0)
        assert breakdown['inventory_score'] == 20.0
        assert breakdown['reported_inventory_units'] == 0

    def test_donors_view_authenticated_donor_no_name_error(self, app, client):
        """Logged-in donor on /become-a-donor must resolve DonorProfile without NameError."""
        seed_india_wide_demo_dataset(app)

        # Login as Arjun (DONOR role)
        client.post('/auth/login', data={'email': 'arjun@donor.com', 'password': 'donor123'}, follow_redirects=True)

        res = client.get('/become-a-donor')
        assert res.status_code == 200
        assert b"Welcome Back, Arjun" in res.data
        assert b"Points" in res.data

        # Alias route /donors
        res_alias = client.get('/donors')
        assert res_alias.status_code == 200
        assert b"Welcome Back, Arjun" in res_alias.data

    def test_donors_view_empty_dataset_graceful(self, app, client):
        """Visiting donors view with 0 records in database must execute cleanly."""
        res = client.get('/become-a-donor')
        assert res.status_code == 200
        assert b"Be Someone's Reason to Smile." in res.data

        res_alias = client.get('/donors')
        assert res_alias.status_code == 200
        assert b"Be Someone's Reason to Smile." in res_alias.data

    def test_donors_view_privacy_protection_for_visitors(self, app, client):
        """Public visitors to /become-a-donor must not see private phone numbers of registered donors."""
        seed_india_wide_demo_dataset(app)

        res = client.get('/become-a-donor')
        assert res.status_code == 200
        # Check that confidential donor phone numbers are not exposed in public markup
        for dp in DonorProfile.query.filter_by(is_demo=True).all():
            if dp.phone:
                assert dp.phone.encode() not in res.data

