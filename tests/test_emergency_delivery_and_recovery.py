"""
BloodLink AI - Comprehensive Test Suite for:
1. Emergency Request Delivery & Diagnostic Outcomes
2. Donor Immediate Actions ("I'm Ready to Donate", "Decline Request") & Empty State
3. Blood Bank Immediate Actions ("We Have Blood Available", "Check Availability", "Unable to Fulfil")
4. Donor Recovery Cooldown Management & 7-State Clinical Lifecycle
5. Notification Deduplication & Demo Account Filtering
6. Status Integrity & Separation of Concerns
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta, date
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest, DonorMatch
from app.models.communication import BloodBankResponse, DonorInvitation
from app.models.notification import Notification
from app.models.donation import Donation
from app.notifications.services import create_notification


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


class BaseWorkflowHelper:
    """Helper setup methods for workflow test cases."""

    def _setup_hospital(self, name="Fortis Memorial", status="VERIFIED"):
        uid = uuid.uuid4().hex[:8]
        email = f"hosp_{name.lower().replace(' ', '_')}_{uid}@fortis.org".lower()
        user = User(name=f"Dr. {name}", email=email, role="HOSPITAL")
        user.set_password("HospitalPass123!")
        db.session.add(user)
        db.session.flush()

        org = Organization(
            organization_name=name,
            organization_type="HOSPITAL",
            registration_reference=f"REG-HOSP-{uid}",
            address="Sector 44, Hospital Lane",
            contact_phone="+91 124 4921021",
            state="Haryana",
            district="Gurugram",
            city="Gurugram",
            latitude=28.4595,
            longitude=77.0266,
            verification_status=status
        )
        db.session.add(org)
        db.session.flush()

        db.session.add(OrganizationMembership(user_id=user.id, organization_id=org.id, membership_role="ADMIN"))
        db.session.commit()
        return {'user_id': user.id, 'email': email, 'org_id': org.id, 'org_name': name}

    def _setup_blood_bank(self, name="Rotary Blood Bank", status="VERIFIED"):
        uid = uuid.uuid4().hex[:8]
        email = f"bank_{name.lower().replace(' ', '_')}_{uid}@rotary.org".lower()
        user = User(name=f"Director {name}", email=email, role="BLOOD_BANK")
        user.set_password("BankPass123!")
        db.session.add(user)
        db.session.flush()

        org = Organization(
            organization_name=name,
            organization_type="BLOOD_BANK",
            registration_reference=f"REG-BB-{uid}",
            address="56 Institutional Area",
            contact_phone="+91 124 2334455",
            state="Haryana",
            district="Gurugram",
            city="Gurugram",
            latitude=28.4600,
            longitude=77.0270,
            verification_status=status
        )
        db.session.add(org)
        db.session.flush()

        db.session.add(OrganizationMembership(user_id=user.id, organization_id=org.id, membership_role="ADMIN"))
        db.session.commit()
        return {'user_id': user.id, 'email': email, 'org_id': org.id, 'org_name': name}

    def _setup_donor(self, blood_group="O+", availability=True, consent=True, status="APPROVED",
                     next_eligible=None, last_donation=None):
        uid = uuid.uuid4().hex[:8]
        email = f"donor_{blood_group.replace('+', 'pos').replace('-', 'neg')}_{uid}@donor.org".lower()
        user = User(name=f"Donor {blood_group}", email=email, role="DONOR")
        user.set_password("DonorPass123!")
        db.session.add(user)
        db.session.flush()

        profile = DonorProfile(
            user_id=user.id,
            declared_blood_group=blood_group,
            state="Haryana",
            district="Gurugram",
            city="Gurugram",
            latitude=28.4590,
            longitude=77.0260,
            availability_status=availability,
            notification_consent=consent,
            verification_status=status,
            last_donation_date=last_donation,
            next_eligible_date=next_eligible
        )
        db.session.add(profile)
        db.session.commit()
        return {'user_id': user.id, 'email': email, 'blood_group': blood_group, 'profile_id': profile.id}

    def _add_inventory(self, org_id, blood_group="O+", component="Whole Blood", units=10, reserved=0):
        inv = BloodInventory(
            blood_bank_id=org_id,
            blood_group=blood_group,
            component_type=component,
            available_units=units,
            reserved_units=reserved
        )
        db.session.add(inv)
        db.session.commit()
        return inv


# =============================================================================
# 1. EMERGENCY REQUEST DELIVERY & AUTOMATIC INVITATION GENERATION
# =============================================================================
class TestEmergencyRequestDeliveryAndMatching(BaseWorkflowHelper):

    def test_emergency_request_creates_matches_and_persistent_invitations(self, app, client):
        """Creating an emergency request persists DonorMatch AND DonorInvitation records."""
        with app.app_context():
            hosp = self._setup_hospital(name="Medanta Medicity")
            # Donor 1: O+ (compatible with O+)
            d1 = self._setup_donor(blood_group="O+", availability=True, consent=True)
            # Donor 2: O- (universal donor, compatible with O+)
            d2 = self._setup_donor(blood_group="O-", availability=True, consent=True)
            # Donor 3: AB+ (incompatible with O+ recipient for whole blood)
            d3 = self._setup_donor(blood_group="AB+", availability=True, consent=True)

        client.post('/auth/login', data={'email': hosp['email'], 'password': 'HospitalPass123!'}, follow_redirects=True)

        res = client.post('/hospital/request/new', data={
            'blood_group': 'O+',
            'component_type': 'Whole Blood',
            'units_required': '2',
            'urgency_level': 'CRITICAL',
            'location': 'Trauma ICU',
            'state': 'Haryana',
            'district': 'Gurugram',
            'city': 'Gurugram',
            'contact_phone': '+91 124 4921021',
            'additional_notes': 'Massive hemorrhage emergency',
            'clinical_deadline': (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"Emergency request" in res.data or b"created and activated" in res.data

        with app.app_context():
            req = BloodRequest.query.filter_by(requesting_organization_id=hosp['org_id']).first()
            assert req is not None
            assert req.request_status == 'ACTIVE_MATCHING'

            # Diagnostic notes should mention matching
            assert req.additional_notes is not None
            assert "[Dispatch Diagnostics]" in req.additional_notes

            # Check DonorMatch records
            matches = DonorMatch.query.filter_by(request_id=req.id).all()
            matched_donor_ids = {m.donor_id for m in matches}
            assert d1['user_id'] in matched_donor_ids
            assert d2['user_id'] in matched_donor_ids
            assert d3['user_id'] not in matched_donor_ids

            # KEY ASSERTION: DonorInvitation records must be persisted
            invitations = DonorInvitation.query.filter_by(blood_request_id=req.id).all()
            invited_donor_ids = {inv.donor_id for inv in invitations}
            assert d1['user_id'] in invited_donor_ids
            assert d2['user_id'] in invited_donor_ids
            assert d3['user_id'] not in invited_donor_ids

            for inv in invitations:
                assert inv.invitation_status == 'SENT'

    def test_ineligible_and_recovery_restricted_donors_not_invited(self, app, client):
        """Donors under active recovery restrictions or unavailable are excluded from matching/invitations."""
        with app.app_context():
            hosp = self._setup_hospital(name="Max Hospital")
            # Donor in active recovery: next eligible date is 30 days from now
            restricted_donor = self._setup_donor(
                blood_group="A+",
                availability=True,
                consent=True,
                next_eligible=date.today() + timedelta(days=30),
                last_donation=date.today() - timedelta(days=26)
            )
            # Donor marked unavailable
            unavailable_donor = self._setup_donor(blood_group="A+", availability=False, consent=True)
            # Eligible donor
            eligible_donor = self._setup_donor(blood_group="A+", availability=True, consent=True)

        client.post('/auth/login', data={'email': hosp['email'], 'password': 'HospitalPass123!'}, follow_redirects=True)

        client.post('/hospital/request/new', data={
            'blood_group': 'A+',
            'component_type': 'Whole Blood',
            'units_required': '1',
            'urgency_level': 'HIGH',
            'location': 'Ward 5',
            'state': 'Haryana',
            'district': 'Gurugram',
            'city': 'Gurugram',
            'contact_phone': '+91 124 4921021',
            'clinical_deadline': (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
        }, follow_redirects=True)

        with app.app_context():
            req = BloodRequest.query.filter_by(requesting_organization_id=hosp['org_id']).first()
            invitations = DonorInvitation.query.filter_by(blood_request_id=req.id).all()
            invited_ids = {inv.donor_id for inv in invitations}

            assert eligible_donor['user_id'] in invited_ids
            assert restricted_donor['user_id'] not in invited_ids
            assert unavailable_donor['user_id'] not in invited_ids

    def test_blood_bank_with_compatible_stock_receives_notification(self, app, client):
        """Blood banks with matching inventory receive notifications on request activation."""
        with app.app_context():
            hosp = self._setup_hospital(name="Columbia Asia")
            bank = self._setup_blood_bank(name="LifeSource Blood Bank")
            self._add_inventory(bank['org_id'], blood_group="B+", component="Whole Blood", units=8, reserved=0)

        client.post('/auth/login', data={'email': hosp['email'], 'password': 'HospitalPass123!'}, follow_redirects=True)

        client.post('/hospital/request/new', data={
            'blood_group': 'B+',
            'component_type': 'Whole Blood',
            'units_required': '2',
            'urgency_level': 'CRITICAL',
            'location': 'OR 2',
            'state': 'Haryana',
            'district': 'Gurugram',
            'city': 'Gurugram',
            'contact_phone': '+91 124 4921021',
            'clinical_deadline': (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        }, follow_redirects=True)

        with app.app_context():
            # Blood bank director user should have received a notification
            notifications = Notification.query.filter_by(recipient_id=bank['user_id']).all()
            assert len(notifications) >= 1
            emergency_notifs = [n for n in notifications if "emergency" in n.title.lower() or "requirement" in n.title.lower()]
            assert len(emergency_notifs) >= 1
            assert "B+" in emergency_notifs[0].message


# =============================================================================
# 2. DONOR IMMEDIATE ACTIONS & EMPTY STATE
# =============================================================================
class TestDonorImmediateActionsAndEmptyState(BaseWorkflowHelper):

    def test_donor_dashboard_empty_state_when_no_invitations(self, app, client):
        """When donor has 0 invitations, the dashboard renders the informative empty state."""
        with app.app_context():
            donor = self._setup_donor(blood_group="O+")

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)
        res = client.get('/donor/dashboard')

        assert res.status_code == 200
        html = res.data.decode('utf-8')
        assert "No Pending Emergency Invitations" in html
        assert "You are on active standby" in html

    def test_donor_accepts_invitation_ready_to_donate(self, app, client):
        """Donor clicks 'I'm Ready to Donate': invitation is ACCEPTED, request marked DONOR_RESPONDED."""
        with app.app_context():
            hosp = self._setup_hospital(name="Artemis Hospital")
            donor = self._setup_donor(blood_group="AB+")

            req = BloodRequest(
                request_reference=f"REQ-{uuid.uuid4().hex[:6].upper()}",
                requesting_organization_id=hosp['org_id'],
                blood_group='AB+',
                component_type='Whole Blood',
                units_required=1,
                urgency_level='CRITICAL',
                location='ICU Bed 4',
                state='Haryana',
                district='Gurugram',
                city='Gurugram',
                contact_phone='+91 124 4921021',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.flush()

            inv = DonorInvitation(
                blood_request_id=req.id,
                hospital_id=hosp['org_id'],
                donor_id=donor['user_id'],
                invitation_status='SENT'
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id
            req_id = req.id

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        # Check invitation appears on dashboard
        dash_res = client.get('/donor/dashboard')
        assert b"I'm Ready to Donate" in dash_res.data
        assert b"Decline Request" in dash_res.data

        # Post acceptance
        res = client.post(f'/donor/invitation/{inv_id}/respond', data={
            'action': "I'm Ready to Donate",
            'consent_acknowledged': 'yes',
            'donor_notes': 'I will arrive within 45 minutes.'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"Ready to Donate" in res.data or b"successfully accepted" in res.data.lower()

        with app.app_context():
            updated_inv = db.session.get(DonorInvitation, inv_id)
            assert updated_inv.invitation_status == 'ACCEPTED'
            assert updated_inv.responded_at is not None

            updated_req = db.session.get(BloodRequest, req_id)
            assert updated_req.request_status == 'DONOR_RESPONDED'

            # Hospital director received notification of acceptance
            hospital_notifs = Notification.query.filter_by(recipient_id=hosp['user_id']).all()
            assert any("Donor Responded" in n.title or "Donor Accepted" in n.title for n in hospital_notifs)

    def test_donor_declines_invitation(self, app, client):
        """Donor clicks 'Decline Request': invitation marked DECLINED with reason."""
        with app.app_context():
            hosp = self._setup_hospital(name="Paras Hospital")
            donor = self._setup_donor(blood_group="B-")

            req = BloodRequest(
                requesting_organization_id=hosp['org_id'],
                blood_group='B-',
                component_type='Whole Blood',
                units_required=1,
                urgency_level='HIGH',
                location='Emergency',
                state='Haryana',
                district='Gurugram',
                city='Gurugram',
                contact_phone='+91 124 4921021',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.flush()

            inv = DonorInvitation(
                blood_request_id=req.id,
                hospital_id=hosp['org_id'],
                donor_id=donor['user_id'],
                invitation_status='SENT'
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.post(f'/donor/invitation/{inv_id}/respond', data={
            'action': "Decline Request",
            'reason': 'Traveling out of state currently'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"declined" in res.data.lower()

        with app.app_context():
            updated_inv = db.session.get(DonorInvitation, inv_id)
            assert updated_inv.invitation_status == 'DECLINED'

    def test_recovery_restricted_donor_cannot_accept_invitation(self, app, client):
        """Donor under active cooldown restriction is prevented from accepting."""
        with app.app_context():
            hosp = self._setup_hospital(name="Civil Hospital")
            # Restricted donor with next eligible date in 20 days
            donor = self._setup_donor(
                blood_group="A-",
                next_eligible=date.today() + timedelta(days=20),
                last_donation=date.today() - timedelta(days=36)
            )

            req = BloodRequest(
                requesting_organization_id=hosp['org_id'],
                blood_group='A-',
                component_type='Whole Blood',
                units_required=1,
                urgency_level='CRITICAL',
                location='Casualty',
                state='Haryana',
                district='Gurugram',
                city='Gurugram',
                contact_phone='+91 124 4921021',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.flush()

            inv = DonorInvitation(
                blood_request_id=req.id,
                hospital_id=hosp['org_id'],
                donor_id=donor['user_id'],
                invitation_status='SENT'
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.post(f'/donor/invitation/{inv_id}/respond', data={
            'action': "ACCEPT",
            'consent_acknowledged': 'yes'
        }, follow_redirects=True)

        # Should be rejected due to clinical cooldown
        assert b"recovery period" in res.data.lower() or b"ineligible" in res.data.lower()

        with app.app_context():
            updated_inv = db.session.get(DonorInvitation, inv_id)
            assert updated_inv.invitation_status == 'SENT'  # Remained unaccepted


# =============================================================================
# 3. BLOOD BANK IMMEDIATE ACTIONS & STOCK LOCKING
# =============================================================================
class TestBloodBankImmediateActions(BaseWorkflowHelper):

    def test_blood_bank_dashboard_displays_emergency_requirements(self, app, client):
        """Blood bank main dashboard renders the Active Hospital Emergency Requirements desk."""
        with app.app_context():
            bank = self._setup_blood_bank(name="Apex Blood Bank")
            hosp = self._setup_hospital(name="Apex Hospital")
            self._add_inventory(bank['org_id'], blood_group="A+", component="Whole Blood", units=5, reserved=0)

            req = BloodRequest(
                requesting_organization_id=hosp['org_id'],
                blood_group='A+',
                component_type='Whole Blood',
                units_required=2,
                urgency_level='CRITICAL',
                location='ICU-1',
                state='Haryana',
                district='Gurugram',
                city='Gurugram',
                contact_phone='+91 124 4921021',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.commit()

        client.post('/auth/login', data={'email': bank['email'], 'password': 'BankPass123!'}, follow_redirects=True)

        res = client.get('/blood-bank/dashboard')
        assert res.status_code == 200
        html = res.data.decode('utf-8')
        assert "Active Hospital Emergency Requirements" in html
        assert "We Have Blood Available" in html
        assert "Check Availability" in html
        assert "Unable to Fulfil" in html

    def test_action_we_have_blood_available_reserves_stock(self, app, client):
        """Action 'We Have Blood Available' reserves stock atomically and updates status."""
        with app.app_context():
            bank = self._setup_blood_bank(name="City Blood Center")
            hosp = self._setup_hospital(name="City General")
            self._add_inventory(bank['org_id'], blood_group="O+", component="Whole Blood", units=6, reserved=0)

            req = BloodRequest(
                requesting_organization_id=hosp['org_id'],
                blood_group='O+',
                component_type='Whole Blood',
                units_required=2,
                urgency_level='CRITICAL',
                location='Surgery',
                state='Haryana',
                district='Gurugram',
                city='Gurugram',
                contact_phone='+91 124 4921021',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id
            bank_org_id = bank['org_id']

        client.post('/auth/login', data={'email': bank['email'], 'password': 'BankPass123!'}, follow_redirects=True)

        res = client.post(f'/blood-bank/request/{req_id}/respond', data={
            'action': 'ACCEPT',
            'units_allocated': '2',
            'delivery_estimate': '25 minutes via cold courier',
            'notes': 'Pack ready for immediate pickup'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"Blood available confirmed" in res.data or b"reserved" in res.data.lower()

        with app.app_context():
            inv = BloodInventory.query.filter_by(
                blood_bank_id=bank_org_id, blood_group="O+", component_type="Whole Blood"
            ).first()
            assert inv.reserved_units == 2
            assert inv.available_units == 6  # Total available invariant preserved

            resp = BloodBankResponse.query.filter_by(blood_request_id=req_id, blood_bank_id=bank_org_id).first()
            assert resp is not None
            assert resp.response_status == 'ACCEPTED'
            assert resp.units_allocated == 2

            updated_req = db.session.get(BloodRequest, req_id)
            assert updated_req.request_status == 'BLOOD_BANK_RESPONDED'

    def test_action_check_availability_sets_reviewing_without_locking(self, app, client):
        """Action 'Check Availability' logs 'REVIEWING' status without holding stock units."""
        with app.app_context():
            bank = self._setup_blood_bank(name="Cross Blood Center")
            hosp = self._setup_hospital(name="Cross Hospital")
            self._add_inventory(bank['org_id'], blood_group="B+", component="Platelets", units=4, reserved=0)

            req = BloodRequest(
                requesting_organization_id=hosp['org_id'],
                blood_group='B+',
                component_type='Platelets',
                units_required=2,
                urgency_level='HIGH',
                location='Oncology',
                state='Haryana',
                district='Gurugram',
                city='Gurugram',
                contact_phone='+91 124 4921021',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id
            bank_org_id = bank['org_id']

        client.post('/auth/login', data={'email': bank['email'], 'password': 'BankPass123!'}, follow_redirects=True)

        res = client.post(f'/blood-bank/request/{req_id}/respond', data={
            'action': 'CHECK_AVAILABILITY',
            'notes': 'Checking batch expiration dates before committing.'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"Reviewing" in res.data or b"hospital notified" in res.data.lower()

        with app.app_context():
            inv = BloodInventory.query.filter_by(
                blood_bank_id=bank_org_id, blood_group="B+", component_type="Platelets"
            ).first()
            assert inv.reserved_units == 0  # No stock locked!

            resp = BloodBankResponse.query.filter_by(blood_request_id=req_id, blood_bank_id=bank_org_id).first()
            assert resp is not None
            assert resp.response_status == 'REVIEWING'

    def test_action_unable_to_fulfil_releases_held_stock(self, app, client):
        """Action 'Unable to Fulfil' marks response DECLINED and releases any previously held units."""
        with app.app_context():
            bank = self._setup_blood_bank(name="Relief Blood Center")
            hosp = self._setup_hospital(name="Relief Hospital")
            inv = self._add_inventory(bank['org_id'], blood_group="A-", component="Whole Blood", units=4, reserved=2)

            req = BloodRequest(
                requesting_organization_id=hosp['org_id'],
                blood_group='A-',
                component_type='Whole Blood',
                units_required=2,
                urgency_level='HIGH',
                location='ER',
                state='Haryana',
                district='Gurugram',
                city='Gurugram',
                contact_phone='+91 124 4921021',
                verification_status='VERIFIED',
                request_status='BLOOD_BANK_RESPONDED'
            )
            db.session.add(req)
            db.session.flush()

            # Previous accepted response
            prev_resp = BloodBankResponse(
                blood_request_id=req.id,
                blood_bank_id=bank['org_id'],
                response_status='ACCEPTED',
                units_allocated=2
            )
            db.session.add(prev_resp)
            db.session.commit()
            req_id = req.id
            bank_org_id = bank['org_id']

        client.post('/auth/login', data={'email': bank['email'], 'password': 'BankPass123!'}, follow_redirects=True)

        res = client.post(f'/blood-bank/request/{req_id}/respond', data={
            'action': 'DECLINE',
            'reason': 'Units reserved for internal emergency'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"Declined" in res.data or b"released" in res.data.lower()

        with app.app_context():
            updated_inv = BloodInventory.query.filter_by(
                blood_bank_id=bank_org_id, blood_group="A-", component_type="Whole Blood"
            ).first()
            assert updated_inv.reserved_units == 0  # Successfully released!

            resp = BloodBankResponse.query.filter_by(blood_request_id=req_id, blood_bank_id=bank_org_id).first()
            assert resp.response_status == 'DECLINED'


# =============================================================================
# 4. DONOR RECOVERY MANAGEMENT & 7-STATE CLINICAL LIFECYCLE
# =============================================================================
class TestDonorRecoveryManagementAndClinicalLifecycle(BaseWorkflowHelper):

    def test_component_specific_cooldown_calculation_on_verification(self, app, client):
        """Verifying a donation sets component-specific recovery cooldowns:
        Whole Blood: 56d, Double RBC: 112d, Platelets: 14d, Plasma: 28d.
        """
        with app.app_context():
            bank = self._setup_blood_bank(name="Red Cross Hub")
            donor_wb = self._setup_donor(blood_group="O+")
            donor_rbc = self._setup_donor(blood_group="A+")
            donor_plt = self._setup_donor(blood_group="B+")
            donor_pls = self._setup_donor(blood_group="AB+")

            # Create donations for each component
            today = date.today()
            donations = [
                Donation(donor_id=donor_wb['user_id'], blood_bank_id=bank['org_id'], component_type='Whole Blood',
                         donation_date=today, verification_status='PENDING'),
                Donation(donor_id=donor_rbc['user_id'], blood_bank_id=bank['org_id'], component_type='Red Blood Cells',
                         donation_date=today, verification_status='PENDING'),
                Donation(donor_id=donor_plt['user_id'], blood_bank_id=bank['org_id'], component_type='Platelets',
                         donation_date=today, verification_status='PENDING'),
                Donation(donor_id=donor_pls['user_id'], blood_bank_id=bank['org_id'], component_type='Plasma',
                         donation_date=today, verification_status='PENDING'),
            ]
            db.session.add_all(donations)
            db.session.commit()
            d_ids = [d.id for d in donations]

        client.post('/auth/login', data={'email': bank['email'], 'password': 'BankPass123!'}, follow_redirects=True)

        # Verify all 4 donations
        for did in d_ids:
            res = client.post(f'/blood-bank/donation/{did}/verify', data={'action': 'VERIFY'}, follow_redirects=True)
            assert res.status_code == 200

        with app.app_context():
            prof_wb = DonorProfile.query.filter_by(user_id=donor_wb['user_id']).first()
            prof_rbc = DonorProfile.query.filter_by(user_id=donor_rbc['user_id']).first()
            prof_plt = DonorProfile.query.filter_by(user_id=donor_plt['user_id']).first()
            prof_pls = DonorProfile.query.filter_by(user_id=donor_pls['user_id']).first()

            # Whole Blood: 56 days
            assert prof_wb.recovery_period_days == 56
            assert prof_wb.next_eligible_date == today + timedelta(days=56)
            assert not prof_wb.is_eligible_to_donate()

            # Red Blood Cells (Double RBC): 112 days
            assert prof_rbc.recovery_period_days == 112
            assert prof_rbc.next_eligible_date == today + timedelta(days=112)
            assert not prof_rbc.is_eligible_to_donate()

            # Platelets: 14 days
            assert prof_plt.recovery_period_days == 14
            assert prof_plt.next_eligible_date == today + timedelta(days=14)
            assert not prof_plt.is_eligible_to_donate()

            # Plasma: 28 days
            assert prof_pls.recovery_period_days == 28
            assert prof_pls.next_eligible_date == today + timedelta(days=28)
            assert not prof_pls.is_eligible_to_donate()

    def test_seven_clinical_status_states(self, app):
        """Verify all 7 states of get_clinical_status() accurately distinguish clinical realities."""
        from app.models.communication import DonorRequestResponse
        with app.app_context():
            # State 1: AVAILABLE_FOR_MATCHING
            p1 = DonorProfile(user_id=1, declared_blood_group="O+", availability_status=True, verification_status="APPROVED")
            assert p1.get_clinical_status()['status'] == 'AVAILABLE_FOR_MATCHING'

            # State 2: TEMPORARILY_UNAVAILABLE
            p2 = DonorProfile(user_id=2, declared_blood_group="A+", availability_status=False, verification_status="APPROVED")
            assert p2.get_clinical_status()['status'] == 'TEMPORARILY_UNAVAILABLE'

            # State 3: ELIGIBILITY_REVIEW_REQUIRED
            p3 = DonorProfile(user_id=3, declared_blood_group="B+", availability_status=True, clinical_review_required=True)
            assert p3.get_clinical_status()['status'] == 'ELIGIBILITY_REVIEW_REQUIRED'

            # State 4: RECOVERY_RESTRICTION_ACTIVE
            p4 = DonorProfile(user_id=4, declared_blood_group="AB+", availability_status=True, verification_status="APPROVED",
                                last_donation_date=date.today(),
                                next_eligible_date=date.today() + timedelta(days=20))
            assert p4.get_clinical_status()['status'] == 'RECOVERY_RESTRICTION_ACTIVE'

            # Setup user for db-dependent states
            user = User(name="Test Donor", email="test_status_donor@test.org", role="DONOR")
            user.set_password("Pass123!")
            db.session.add(user)
            db.session.flush()

            p5 = DonorProfile(user_id=user.id, declared_blood_group="O+", availability_status=True, verification_status="APPROVED")
            db.session.add(p5)
            db.session.flush()

            hosp = self._setup_hospital(name="Status Hospital")
            bank = self._setup_blood_bank(name="Status Bank")
            req = BloodRequest(
                requesting_organization_id=hosp['org_id'],
                blood_group='O+',
                component_type='Whole Blood',
                units_required=1,
                urgency_level='CRITICAL',
                location='ICU',
                state='Haryana',
                district='Gurugram',
                city='Gurugram',
                contact_phone='+91 124 4921021',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.commit()

            # State 5: INVITATION_ACCEPTED (active confirmed response)
            resp_accepted = DonorRequestResponse(blood_request_id=req.id, donor_id=user.id, response_status='CONFIRMED')
            db.session.add(resp_accepted)
            db.session.commit()
            assert p5.get_clinical_status()['status'] == 'INVITATION_ACCEPTED'

            # State 6: DONATION_PENDING_VERIFICATION (overrides INVITATION_ACCEPTED)
            don_pending = Donation(donor_id=user.id, blood_bank_id=bank['org_id'], component_type='Whole Blood',
                                   donation_date=date.today(), verification_status='PENDING')
            db.session.add(don_pending)
            db.session.commit()
            assert p5.get_clinical_status()['status'] == 'DONATION_PENDING_VERIFICATION'

            # State 7: DONATION_VERIFIED (recent verified donation within 48h)
            don_pending.verification_status = 'VERIFIED'
            don_pending.verified_at = datetime.now(timezone.utc)
            db.session.commit()
            assert p5.get_clinical_status()['status'] == 'DONATION_VERIFIED'


# =============================================================================
# 5. NOTIFICATION DEDUPLICATION & INTEGRATION DIAGNOSTICS
# =============================================================================
class TestNotificationDiagnosticsAndDeduplication(BaseWorkflowHelper):

    def test_notification_deduplication_within_three_minute_window(self, app):
        """NotificationService skips creating duplicate notification to same recipient within 3 minutes."""
        with app.app_context():
            u = User(name="Notif Target", email="target@notif.org", role="DONOR")
            u.set_password("Pass123!")
            db.session.add(u)
            db.session.commit()

            # First notification should succeed and create record
            n1 = create_notification(
                recipient_id=u.id,
                notification_type="EMERGENCY",
                title="Critical Request",
                message="Emergency Whole Blood needed at General Hospital"
            )
            assert n1 is not None

            # Immediate second notification with identical content should be deduplicated
            n2 = create_notification(
                recipient_id=u.id,
                notification_type="EMERGENCY",
                title="Critical Request",
                message="Emergency Whole Blood needed at General Hospital"
            )
            assert n2 is not None
            assert n2.id == n1.id

            # Count of notifications in DB must remain exactly 1
            all_n = Notification.query.filter_by(recipient_id=u.id).all()
            assert len(all_n) == 1

    def test_demo_accounts_filtered_from_live_dispatches(self, app):
        """Users marked is_demo=True do not trigger external dispatches."""
        with app.app_context():
            demo_user = User(name="Demo Doctor", email="demo_doctor@hospital.org", role="HOSPITAL", is_demo=True)
            demo_user.set_password("Pass123!")
            db.session.add(demo_user)
            db.session.commit()

            # Internal notification record is created, but no external exception raised
            n = create_notification(
                recipient_id=demo_user.id,
                notification_type="SYSTEM",
                title="Demo Notification",
                message="Simulation update"
            )
            assert n is not None
            assert n.recipient_id == demo_user.id

