import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.request import BloodRequest
from app.models.communication import DonorInvitation, DonorRequestResponse
from app.services.donor_matching_service import search_matching_donors


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


class TestHospitalMatchingDonors:
    """Rigorous test suite for Find Matching Donors in Hospital Dashboard."""

    # =========================================================================
    # 1. ACCESS CONTROL AND ROLE ENFORCEMENT
    # =========================================================================
    def test_unauthenticated_and_donor_access_rejected(self, app, client):
        """Unauthenticated visitors and donors are strictly prohibited from accessing hospital donor search."""
        # Unauthenticated access rejected
        res = client.get('/hospital/find-donors')
        assert res.status_code in (302, 401)

        # Donor accessing hospital route is forbidden (403)
        with app.app_context():
            donor = User(name="Test Donor", email="donor@test.com", role="DONOR")
            donor.set_password("Pass123!")
            db.session.add(donor)
            db.session.commit()

        client.post('/auth/login', data={'email': 'donor@test.com', 'password': 'Pass123!'}, follow_redirects=True)
        res_donor = client.get('/hospital/find-donors')
        assert res_donor.status_code == 403

    def test_approved_hospital_can_access_search(self, app, client):
        """Verified hospital staff can successfully access /hospital/find-donors."""
        with app.app_context():
            hosp_user = User(name="Dr. Staff", email="staff@hospital.org", role="HOSPITAL")
            hosp_user.set_password("Hosp123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="City General Hospital",
                organization_type="HOSPITAL",
                registration_reference="HOSP-CGH-01",
                address="100 Hospital Way",
                contact_phone="+91 80 1122 3344",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                latitude=12.9716,
                longitude=77.5946,
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()
            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))
            db.session.commit()

        client.post('/auth/login', data={'email': 'staff@hospital.org', 'password': 'Hosp123!'}, follow_redirects=True)
        res = client.get('/hospital/find-donors')
        assert res.status_code == 200
        assert b"Find Matching Donors" in res.data
        assert b"City General Hospital" in res.data
        assert b"Required Blood Group" in res.data

    # =========================================================================
    # 2. MATCHING ALGORITHM FILTERS: COMPATIBILITY, AVAILABILITY, DISTANCE
    # =========================================================================
    def test_blood_compatibility_filtering(self, app, client):
        """Donors are filtered strictly by preliminary blood component compatibility rules."""
        with app.app_context():
            hosp_user = User(name="Hospital Admin", email="admin@hosp.org", role="HOSPITAL")
            hosp_user.set_password("Pass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="Apex Care Center",
                organization_type="HOSPITAL",
                registration_reference="APEX-01",
                address="22 MG Road",
                contact_phone="+91 80 5555 1234",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                latitude=12.9716,
                longitude=77.5946,
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()
            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            # Setup donors with different blood groups
            # Donor 1: O- (Universal donor for Whole Blood / RBC)
            d1 = User(name="Donor O Negative", email="o_neg@donor.org", role="DONOR")
            d1.set_password("Pass123!")
            db.session.add(d1)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d1.id, declared_blood_group="O-", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", latitude=12.9720, longitude=77.5950,
                availability_status=True, notification_consent=True, verification_status="APPROVED"
            ))

            # Donor 2: A+ (Compatible with A+, AB+)
            d2 = User(name="Donor A Positive", email="a_pos@donor.org", role="DONOR")
            d2.set_password("Pass123!")
            db.session.add(d2)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d2.id, declared_blood_group="A+", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", latitude=12.9720, longitude=77.5950,
                availability_status=True, notification_consent=True, verification_status="APPROVED"
            ))

            # Donor 3: B+ (Incompatible with A+)
            d3 = User(name="Donor B Positive", email="b_pos@donor.org", role="DONOR")
            d3.set_password("Pass123!")
            db.session.add(d3)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d3.id, declared_blood_group="B+", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", latitude=12.9720, longitude=77.5950,
                availability_status=True, notification_consent=True, verification_status="APPROVED"
            ))
            db.session.commit()

        client.post('/auth/login', data={'email': 'admin@hosp.org', 'password': 'Pass123!'}, follow_redirects=True)

        # Search for A+ Whole Blood:
        # Compatible donors: A+, A-, O+, O-
        # Should include: Donor O Negative (O-) and Donor A Positive (A+)
        # Should exclude: Donor B Positive (B+)
        res = client.get('/hospital/find-donors?blood_group=A%2B&component_type=Whole+Blood')
        assert res.status_code == 200
        assert b"Donor A Positive" in res.data
        assert b"Donor O Negative" in res.data
        assert b"Donor B Positive" not in res.data

    def test_availability_and_notification_consent_filtering(self, app, client):
        """Unavailable donors and donors who opted out of notifications are excluded appropriately."""
        with app.app_context():
            hosp_user = User(name="Hospital Admin", email="admin2@hosp.org", role="HOSPITAL")
            hosp_user.set_password("Pass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="Care Hospital",
                organization_type="HOSPITAL",
                registration_reference="CARE-01",
                address="45 Road",
                contact_phone="+91 80 1234 9999",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()
            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            # Available donor with consent
            d1 = User(name="Available Donor", email="avail@donor.org", role="DONOR")
            d1.set_password("Pass123!")
            db.session.add(d1)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d1.id, declared_blood_group="O+", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", availability_status=True, notification_consent=True, verification_status="APPROVED"
            ))

            # Unavailable donor
            d2 = User(name="Unavailable Donor", email="unavail@donor.org", role="DONOR")
            d2.set_password("Pass123!")
            db.session.add(d2)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d2.id, declared_blood_group="O+", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", availability_status=False, notification_consent=True, verification_status="APPROVED"
            ))

            # Donor who opted out of notifications
            d3 = User(name="No Consent Donor", email="noconsent@donor.org", role="DONOR")
            d3.set_password("Pass123!")
            db.session.add(d3)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d3.id, declared_blood_group="O+", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", availability_status=True, notification_consent=False, verification_status="APPROVED"
            ))
            db.session.commit()

        client.post('/auth/login', data={'email': 'admin2@hosp.org', 'password': 'Pass123!'}, follow_redirects=True)

        # 1. Default search: availability=available
        # Available Donor must be present; Unavailable Donor and No Consent Donor must be excluded
        res_avail = client.get('/hospital/find-donors?blood_group=O%2B&availability=available')
        assert res_avail.status_code == 200
        assert b"Available Donor" in res_avail.data
        assert b"Unavailable Donor" not in res_avail.data
        assert b"No Consent Donor" not in res_avail.data

        # 2. Search availability=all:
        # Includes Unavailable Donor, but No Consent Donor is STILL excluded (consent is mandatory)
        res_all = client.get('/hospital/find-donors?blood_group=O%2B&availability=all')
        assert res_all.status_code == 200
        assert b"Available Donor" in res_all.data
        assert b"Unavailable Donor" in res_all.data
        assert b"No Consent Donor" not in res_all.data

    def test_distance_and_missing_location_filtering(self, app, client):
        """Distance radius filter excludes farther donors and handles missing coordinates without inventing distances."""
        with app.app_context():
            hosp_user = User(name="Hospital Staff", email="dist_staff@hosp.org", role="HOSPITAL")
            hosp_user.set_password("Pass123!")
            db.session.add(hosp_user)
            db.session.flush()

            # Center: Bengaluru coordinates (12.9716, 77.5946)
            hosp = Organization(
                organization_name="Distance Test Hospital",
                organization_type="HOSPITAL",
                registration_reference="DIST-01",
                address="Central Circle",
                contact_phone="+91 80 7777 8888",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                latitude=12.9716,
                longitude=77.5946,
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()
            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            # Donor Nearby: ~2 km away (12.9800, 77.6000)
            d_near = User(name="Nearby Donor", email="near@donor.org", role="DONOR")
            d_near.set_password("Pass123!")
            db.session.add(d_near)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d_near.id, declared_blood_group="B-", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", latitude=12.9800, longitude=77.6000,
                availability_status=True, notification_consent=True, verification_status="APPROVED"
            ))

            # Donor Far: ~40 km away (13.3300, 77.5946)
            d_far = User(name="Faraway Donor", email="far@donor.org", role="DONOR")
            d_far.set_password("Pass123!")
            db.session.add(d_far)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d_far.id, declared_blood_group="B-", state="Karnataka", district="Bengaluru Rural",
                city="Doddaballapur", latitude=13.3300, longitude=77.5946,
                availability_status=True, notification_consent=True, verification_status="APPROVED"
            ))

            # Donor with Missing Location (no coordinates)
            d_nocoord = User(name="No Coordinates Donor", email="nocoord@donor.org", role="DONOR")
            d_nocoord.set_password("Pass123!")
            db.session.add(d_nocoord)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d_nocoord.id, declared_blood_group="B-", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", latitude=None, longitude=None,
                availability_status=True, notification_consent=True, verification_status="APPROVED"
            ))
            db.session.commit()

        client.post('/auth/login', data={'email': 'dist_staff@hosp.org', 'password': 'Pass123!'}, follow_redirects=True)

        # 1. Search with max_distance=10 km:
        # Nearby Donor (~2 km) must be included.
        # Faraway Donor (~40 km) must be excluded.
        # No Coordinates Donor must be excluded (cannot verify within 10 km without coordinates).
        res_10km = client.get('/hospital/find-donors?blood_group=B-&max_distance=10')
        assert res_10km.status_code == 200
        assert b"Nearby Donor" in res_10km.data
        assert b"Faraway Donor" not in res_10km.data
        assert b"No Coordinates Donor" not in res_10km.data

        # 2. Search with max_distance=50 km:
        # Faraway Donor (~40 km) must now be included!
        res_50km = client.get('/hospital/find-donors?blood_group=B-&max_distance=50')
        assert res_50km.status_code == 200
        assert b"Nearby Donor" in res_50km.data
        assert b"Faraway Donor" in res_50km.data
        assert b"No Coordinates Donor" not in res_50km.data

        # 3. Search with Any Distance (empty max_distance):
        # All 3 donors included, and No Coordinates Donor displays "Location not specified"
        res_any = client.get('/hospital/find-donors?blood_group=B-&max_distance=')
        assert res_any.status_code == 200
        assert b"Nearby Donor" in res_any.data
        assert b"Faraway Donor" in res_any.data
        assert b"No Coordinates Donor" in res_any.data
        assert b"Location not specified" in res_any.data

    def test_unverified_donors_excluded(self, app, client):
        """Unverified, suspended, or rejected donor accounts are strictly excluded from hospital matching."""
        with app.app_context():
            hosp_user = User(name="Hospital Staff", email="audit_staff@hosp.org", role="HOSPITAL")
            hosp_user.set_password("Pass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="Trust Hospital",
                organization_type="HOSPITAL",
                registration_reference="TRUST-01",
                address="12 Main Rd",
                contact_phone="+91 80 3344 5566",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()
            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            # Pending verification donor
            d_pending = User(name="Pending Donor", email="pending@donor.org", role="DONOR")
            d_pending.set_password("Pass123!")
            db.session.add(d_pending)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d_pending.id, declared_blood_group="AB-", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", availability_status=True, notification_consent=True,
                verification_status="PENDING_VERIFICATION"
            ))

            # Suspended donor
            d_susp = User(name="Suspended Donor", email="susp@donor.org", role="DONOR")
            d_susp.set_password("Pass123!")
            db.session.add(d_susp)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d_susp.id, declared_blood_group="AB-", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", availability_status=True, notification_consent=True,
                verification_status="SUSPENDED"
            ))

            # Approved donor
            d_appr = User(name="Approved Donor", email="appr@donor.org", role="DONOR")
            d_appr.set_password("Pass123!")
            db.session.add(d_appr)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=d_appr.id, declared_blood_group="AB-", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", availability_status=True, notification_consent=True,
                verification_status="APPROVED"
            ))
            db.session.commit()

        client.post('/auth/login', data={'email': 'audit_staff@hosp.org', 'password': 'Pass123!'}, follow_redirects=True)
        res = client.get('/hospital/find-donors?blood_group=AB-')
        assert res.status_code == 200
        assert b"Approved Donor" in res.data
        assert b"Pending Donor" not in res.data
        assert b"Suspended Donor" not in res.data

    # =========================================================================
    # 3. DIRECT INVITATION WORKFLOW AND DUPLICATE PREVENTION
    # =========================================================================
    def test_send_invitation_and_duplicate_prevention(self, app, client):
        """Hospital dispatches invitation, duplicate invitations are blocked, and donor can accept or decline."""
        with app.app_context():
            hosp_user = User(name="Hospital Dispatcher", email="dispatch@hosp.org", role="HOSPITAL")
            hosp_user.set_password("Pass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="Emergency Trauma Center",
                organization_type="HOSPITAL",
                registration_reference="TRAUMA-01",
                address="7 Bypass Rd",
                contact_phone="+91 80 9999 1111",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()
            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            # Create an active blood request
            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp.id,
                blood_group="O+",
                component_type="Whole Blood",
                units_required=2,
                urgency_level="CRITICAL",
                location="ICU Trauma Unit",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                contact_phone="+91 80 9999 1111",
                verification_status="VERIFIED",
                request_status="OPEN"
            )
            db.session.add(req)

            # Create eligible voluntary donor
            donor_user = User(name="Kavita Volunteer", email="kavita@donor.org", role="DONOR")
            donor_user.set_password("Pass123!")
            db.session.add(donor_user)
            db.session.flush()
            db.session.add(DonorProfile(
                user_id=donor_user.id, declared_blood_group="O+", state="Karnataka", district="Bengaluru Urban",
                city="Bengaluru", availability_status=True, notification_consent=True, verification_status="APPROVED"
            ))
            db.session.commit()

            req_id = req.id
            donor_id = donor_user.id

        # 1. Hospital sends blood request via /hospital/send-invitation
        client.post('/auth/login', data={'email': 'dispatch@hosp.org', 'password': 'Pass123!'}, follow_redirects=True)
        res_send = client.post('/hospital/send-invitation', data={
            'donor_id': donor_id,
            'blood_request_id': req_id,
            'message': 'Immediate requirement for emergency surgery at Trauma Center Ward 2.'
        }, follow_redirects=True)
        assert res_send.status_code == 200
        assert b"invitation successfully dispatched" in res_send.data

        # Verify DB invitation record
        with app.app_context():
            inv = DonorInvitation.query.filter_by(blood_request_id=req_id, donor_id=donor_id).first()
            assert inv is not None
            assert inv.invitation_status == 'SENT'
            inv_id = inv.id

        # 2. Duplicate Invitation Prevention: Second invitation submission is rejected
        res_dup = client.post('/hospital/send-invitation', data={
            'donor_id': donor_id,
            'blood_request_id': req_id
        }, follow_redirects=True)
        assert res_dup.status_code == 200
        assert b"already been dispatched" in res_dup.data

        # Verify DB uniqueness constraint
        with app.app_context():
            count = DonorInvitation.query.filter_by(blood_request_id=req_id, donor_id=donor_id).count()
            assert count == 1, "Duplicate invitation record must be strictly prevented!"

        # 3. Donor declines invitation
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'kavita@donor.org', 'password': 'Pass123!'}, follow_redirects=True)
        res_decline = client.post(f'/donor/invitation/{inv_id}/respond', data={'action': 'DECLINE'}, follow_redirects=True)
        assert res_decline.status_code == 200
        assert b"declined the donation invitation" in res_decline.data

        with app.app_context():
            inv = db.session.get(DonorInvitation, inv_id)
            assert inv.invitation_status == 'DECLINED'

    # =========================================================================
    # 4. RESTRICTED DONOR PROFILE PREVIEW & IDOR PROTECTION
    # =========================================================================
    def test_restricted_donor_profile_preview(self, app, client):
        """Authorized hospital can preview donor coordination summary; sensitive PII is redacted."""
        with app.app_context():
            hosp_user = User(name="Dr. Clinical", email="clinical@hospital.org", role="HOSPITAL")
            hosp_user.set_password("Pass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="Specialty Clinic",
                organization_type="HOSPITAL",
                registration_reference="SPEC-01",
                address="5 Health Hub",
                contact_phone="+91 80 4400 1122",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()
            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            donor_user = User(name="Vikram Senior Donor", email="vikram@donor.org", role="DONOR")
            donor_user.set_password("Pass123!")
            db.session.add(donor_user)
            db.session.flush()

            donor_prof = DonorProfile(
                user_id=donor_user.id,
                declared_blood_group="A-",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                phone="+91 9900011222",
                availability_status=True,
                notification_consent=True,
                verification_status="APPROVED"
            )
            db.session.add(donor_prof)
            db.session.commit()

            donor_id = donor_user.id

        # 1. Hospital previews donor profile
        client.post('/auth/login', data={'email': 'clinical@hospital.org', 'password': 'Pass123!'}, follow_redirects=True)
        res_preview = client.get(f'/hospital/donor/{donor_id}/preview')
        assert res_preview.status_code == 200
        assert b"Restricted Donor Profile Preview" in res_preview.data
        assert b"A-" in res_preview.data
        assert b"Bengaluru" in res_preview.data

        # CRITICAL PRIVACY & SECURITY: Phone number & private credentials MUST NOT be leaked in preview
        assert b"+91 9900011222" not in res_preview.data

        # 2. JSON Endpoint format test (for AJAX modal)
        res_json = client.get(f'/hospital/donor/{donor_id}/preview?format=json')
        assert res_json.status_code == 200
        data = res_json.get_json()
        assert data['donor_id'] == donor_id
        assert data['blood_group'] == 'A-'
        assert 'phone' not in data

        # 3. Invalid donor ID returns 404
        res_404 = client.get('/hospital/donor/999999/preview')
        assert res_404.status_code == 404

    # =========================================================================
    # 5. EMPTY SEARCH RESULTS STATE
    # =========================================================================
    def test_empty_search_results_feedback(self, app, client):
        """Searching with filters that yield no candidates displays helpful guidance."""
        with app.app_context():
            hosp_user = User(name="Hospital Staff", email="search_staff@hosp.org", role="HOSPITAL")
            hosp_user.set_password("Pass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="General Hospital",
                organization_type="HOSPITAL",
                registration_reference="GEN-01",
                address="1 Main St",
                contact_phone="+91 80 1234 0000",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()
            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))
            db.session.commit()

        client.post('/auth/login', data={'email': 'search_staff@hosp.org', 'password': 'Pass123!'}, follow_redirects=True)
        # Search for AB- with a non-existent name query
        res = client.get('/hospital/find-donors?blood_group=AB-&q=NonExistentDonorXYZ')
        assert res.status_code == 200
        assert b"No matching donors found. Try increasing the search radius or changing the search filters." in res.data

    # =========================================================================
    # 6. DYNAMIC SEARCH LOCATION & HOSPITAL PROFILE PRESERVATION
    # =========================================================================
    def test_custom_search_location_and_distance_calculation(self, app, client):
        """Searching around a custom city calculates distance from the custom center and preserves hospital DB record."""
        with app.app_context():
            hosp_user = User(name="Bengaluru Staff", email="bengaluru_staff@hosp.org", role="HOSPITAL")
            hosp_user.set_password("Pass123!")
            db.session.add(hosp_user)
            db.session.flush()

            # Hospital registered in Bengaluru
            hosp = Organization(
                organization_name="Bengaluru Central Hospital",
                organization_type="HOSPITAL",
                registration_reference="BCH-01",
                address="10 MG Road",
                contact_phone="+91 80 9988 7766",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                latitude=12.9716,
                longitude=77.5946,
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()
            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            # Donor 1: In Kochi, Kerala (lat: 9.9312, lon: 76.2673)
            kochi_donor_user = User(name="Kochi Donor O+", email="kochi_donor@test.org", role="DONOR")
            kochi_donor_user.set_password("Pass123!")
            db.session.add(kochi_donor_user)
            db.session.flush()
            kochi_profile = DonorProfile(
                user_id=kochi_donor_user.id,
                declared_blood_group="O+",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                latitude=9.9312,
                longitude=76.2673,
                availability_status=True,
                notification_consent=True,
                verification_status="APPROVED"
            )
            db.session.add(kochi_profile)

            # Donor 2: In Bengaluru, Karnataka (lat: 12.9716, lon: 77.5946)
            blr_donor_user = User(name="BLR Donor O+", email="blr_donor@test.org", role="DONOR")
            blr_donor_user.set_password("Pass123!")
            db.session.add(blr_donor_user)
            db.session.flush()
            blr_profile = DonorProfile(
                user_id=blr_donor_user.id,
                declared_blood_group="O+",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                latitude=12.9716,
                longitude=77.5946,
                availability_status=True,
                notification_consent=True,
                verification_status="APPROVED"
            )
            db.session.add(blr_profile)
            db.session.commit()
            hosp_id = hosp.id

        client.post('/auth/login', data={'email': 'bengaluru_staff@hosp.org', 'password': 'Pass123!'}, follow_redirects=True)

        # 1. Search with custom location Kochi (lat=9.9312, lon=76.2673, max_distance=25 km)
        res_custom = client.get('/hospital/find-donors?blood_group=O+&location_name=Kochi%2C+Kerala&lat=9.9312&lon=76.2673&max_distance=25')
        assert res_custom.status_code == 200
        assert b"Searching Around: Kochi, Kerala" in res_custom.data
        # Kochi donor should be present (distance ~0 km)
        assert b"Kochi Donor" in res_custom.data
        # Bengaluru donor is ~360 km away, so must NOT be in results for max_distance=25
        assert b"BLR Donor" not in res_custom.data

        # 2. Verify hospital registered organization in database is NEVER modified
        with app.app_context():
            hosp_db = db.session.get(Organization, hosp_id)
            assert hosp_db.city == "Bengaluru"
            assert hosp_db.state == "Karnataka"
            assert round(hosp_db.latitude, 4) == 12.9716
            assert round(hosp_db.longitude, 4) == 77.5946

        # 3. Search with fallback city name Kochi without lat/lon query params
        res_fallback = client.get('/hospital/find-donors?blood_group=O+&location_name=Kochi&max_distance=25')
        assert res_fallback.status_code == 200
        assert b"Kochi Donor" in res_fallback.data
        assert b"BLR Donor" not in res_fallback.data
