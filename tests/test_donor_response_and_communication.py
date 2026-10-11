import os
import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest, DonorMatch
from app.models.communication import DonorRequestResponse, DonorInvitation, Conversation, Message
from app.models.verification import VerificationApplication, VerificationDocument
from app.models.audit import AuditLog


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


class TestDonorResponseAndCommunication:
    """Comprehensive test suite for Donor Responses, Hospital Communications,
    Patient Confidentiality, and Administrative Verification Center."""

    # =========================================================================
    # FEATURE 1: DONOR REQUEST RESPONSE SYSTEM
    # =========================================================================
    def test_donor_opportunity_visibility_and_response(self, app, client):
        """Voluntary donors can view opportunities from verified hospitals and respond."""
        with app.app_context():
            # Setup verified hospital
            hosp_user = User(name="Dr. Hospital", email="doc@metrohospital.org", role="HOSPITAL")
            hosp_user.set_password("HospPass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="Metro City Hospital",
                organization_type="HOSPITAL",
                registration_reference="HOSP-METRO-01",
                address="12 Colaba Causeway",
                contact_phone="+91 22 2200 1122",
                state="Maharashtra",
                district="Mumbai City",
                city="Mumbai",
                latitude=18.9220,
                longitude=72.8347,
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()

            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            # Create an active, verified emergency request
            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp.id,
                blood_group="O+",
                component_type="Whole Blood",
                units_required=2,
                urgency_level="CRITICAL",
                location="ICU Trauma Unit",
                state="Maharashtra",
                district="Mumbai City",
                city="Mumbai",
                latitude=18.9220,
                longitude=72.8347,
                verification_status="VERIFIED",
                request_status="OPEN",
                contact_phone="+91 22 2200 1122",
                patient_name="Confidential Patient John Doe",
                patient_reference="MRN-7890"
            )
            db.session.add(req)

            # Create donor
            donor_user = User(name="Amit Donor", email="amit@donor.org", role="DONOR")
            donor_user.set_password("DonorPass123!")
            db.session.add(donor_user)
            db.session.flush()

            donor_prof = DonorProfile(
                user_id=donor_user.id,
                declared_blood_group="O+",
                state="Maharashtra",
                district="Mumbai City",
                city="Mumbai",
                latitude=18.9250,
                longitude=72.8300,
                availability_status=True,
                verification_status="APPROVED",
                notification_consent=True
            )
            db.session.add(donor_prof)
            db.session.commit()
            req_id = req.id

        # 1. Donor logs in and views opportunities
        client.post('/auth/login', data={'email': 'amit@donor.org', 'password': 'DonorPass123!'}, follow_redirects=True)
        res_dash = client.get('/donor/dashboard')
        assert res_dash.status_code == 200
        assert b"Blood Donation Opportunities" in res_dash.data
        assert b"Metro City Hospital" in res_dash.data
        assert b"O+" in res_dash.data
        assert b"I'm Ready to Donate" in res_dash.data

        # CRITICAL PRIVACY CHECK: Patient name and reference MUST NEVER be exposed on donor dashboard
        assert b"Confidential Patient John Doe" not in res_dash.data
        assert b"MRN-7890" not in res_dash.data

        # 2. Donor clicks "I'm Ready to Donate"
        res_resp = client.post(f'/donor/request/{req_id}/respond', follow_redirects=True)
        assert res_resp.status_code == 200
        assert b"has been transmitted to" in res_resp.data

        # Verify DB response record
        with app.app_context():
            resp = DonorRequestResponse.query.filter_by(blood_request_id=req_id).first()
            assert resp is not None
            assert resp.response_status == 'INTERESTED'
            resp_id = resp.id

        # 3. Duplicate Prevention Check: Donor attempting to respond again is prevented
        res_dup = client.post(f'/donor/request/{req_id}/respond', follow_redirects=True)
        assert res_dup.status_code == 200
        assert b"already responded" in res_dup.data

        with app.app_context():
            count = DonorRequestResponse.query.filter_by(blood_request_id=req_id).count()
            assert count == 1, "Duplicate response record must be prevented!"

        # 4. Donor views responses in "My Blood Request Responses" table
        res_dash2 = client.get('/donor/dashboard')
        assert b"My Blood Request Responses" in res_dash2.data
        assert b"INTERESTED" in res_dash2.data
        assert b"Withdraw" in res_dash2.data

        # 5. Donor withdraws response
        res_withdraw = client.post(f'/donor/response/{resp_id}/withdraw', follow_redirects=True)
        assert res_withdraw.status_code == 200
        assert b"Your donation response has been withdrawn" in res_withdraw.data

        with app.app_context():
            resp = db.session.get(DonorRequestResponse, resp_id)
            assert resp.response_status == 'WITHDRAWN'

    # =========================================================================
    # FEATURE 2: HOSPITAL BLOOD REQUEST SEARCH & CLINICAL PRIVACY
    # =========================================================================
    def test_hospital_inventory_search_and_confidential_request(self, app, client):
        """Hospital can search regional blood bank inventory and create requests with confidential patient details."""
        with app.app_context():
            # Setup hospital
            hosp_user = User(name="Dr. Priya Surgeon", email="priya@apollo.org", role="HOSPITAL")
            hosp_user.set_password("ApolloPass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="Apollo Specialty Hospital",
                organization_type="HOSPITAL",
                registration_reference="APOLLO-BLR-01",
                address="154 Bannerghatta Rd",
                contact_phone="+91 80 1234 5678",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()

            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            # Setup verified blood bank with inventory
            bank = Organization(
                organization_name="Rotary TTK Blood Bank",
                organization_type="BLOOD_BANK",
                registration_reference="ROTARY-BLR-01",
                address="10 New Thippasandra",
                contact_phone="+91 80 9876 5432",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                verification_status="VERIFIED"
            )
            db.session.add(bank)
            db.session.flush()

            inv = BloodInventory(
                blood_bank_id=bank.id,
                blood_group="A+",
                component_type="Whole Blood",
                available_units=15
            )
            db.session.add(inv)
            db.session.commit()

        # 1. Hospital logs in
        client.post('/auth/login', data={'email': 'priya@apollo.org', 'password': 'ApolloPass123!'}, follow_redirects=True)

        # 2. Regional stock search across verified blood banks
        res_search = client.get('/hospital/search-inventory?blood_group=A%2B&component=Whole+Blood&state=Karnataka&district=Bengaluru+Urban')
        assert res_search.status_code == 200
        assert b"Rotary TTK Blood Bank" in res_search.data
        assert b"15" in res_search.data

        # 3. Create request with confidential patient fields
        res_create = client.post('/hospital/request/new', data={
            'blood_group': 'A+',
            'component_type': 'Whole Blood',
            'units_required': '3',
            'urgency_level': 'HIGH',
            'location': 'Operating Theater 2',
            'patient_name': 'Secret VIP Patient Patel',
            'patient_reference': 'CASE-VIP-991',
            'contact_phone': '+91 80 1234 5678',
            'additional_notes': 'Cardiac surgery scheduled'
        }, follow_redirects=True)
        assert res_create.status_code == 200
        assert b"created and activated for matching" in res_create.data

        with app.app_context():
            req = BloodRequest.query.filter_by(patient_reference='CASE-VIP-991').first()
            assert req is not None
            assert req.patient_name == 'Secret VIP Patient Patel'
            req_id = req.id

        # 4. Requesting hospital staff CAN view patient details on their own details page
        res_details = client.get(f'/hospital/request/{req_id}')
        assert res_details.status_code == 200
        assert b"Secret VIP Patient Patel" in res_details.data
        assert b"CASE-VIP-991" in res_details.data

        # 5. IDOR & CLINICAL PRIVACY ENFORCEMENT:
        # Create a second, unrelated hospital
        with app.app_context():
            other_user = User(name="Dr. Other", email="other@stjohns.org", role="HOSPITAL")
            other_user.set_password("Pass123!")
            db.session.add(other_user)
            db.session.flush()

            other_hosp = Organization(
                organization_name="St. Johns Hospital",
                organization_type="HOSPITAL",
                registration_reference="STJ-01",
                address="Koramangala 1st Block",
                contact_phone="+91 80 4455 6677",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                verification_status="VERIFIED"
            )
            db.session.add(other_hosp)
            db.session.flush()

            db.session.add(OrganizationMembership(user_id=other_user.id, organization_id=other_hosp.id, membership_role='ADMIN'))
            db.session.commit()

        # Log in as other hospital -> Attempt to access req_id details must be blocked with 403 Forbidden!
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'other@stjohns.org', 'password': 'Pass123!'}, follow_redirects=True)
        res_unauth = client.get(f'/hospital/request/{req_id}')
        assert res_unauth.status_code == 403

        # Model-level privacy method test: get_patient_name() strictly protects confidentiality
        with app.app_context():
            req_check = db.session.get(BloodRequest, req_id)
            unauth_user = User.query.filter_by(email="other@stjohns.org").first()
            assert req_check.get_patient_name(unauth_user) is None, "Unauthorized user must receive None for patient name!"
            assert req_check.get_patient_name(None) is None, "Unauthenticated user must receive None for patient name!"

    # =========================================================================
    # FEATURE 2.E & 2.F: HOSPITAL INVITATIONS AND STATUS UPDATES
    # =========================================================================
    def test_hospital_invitations_and_response_management(self, app, client):
        """Hospital can invite matched donors and manage response transitions."""
        with app.app_context():
            hosp_user = User(name="Hospital Admin", email="admin@fortis.org", role="HOSPITAL")
            hosp_user.set_password("FortisPass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="Fortis Hospital",
                organization_type="HOSPITAL",
                registration_reference="FORTIS-01",
                address="Okhla Road",
                contact_phone="+91 11 4455 6677",
                state="Delhi",
                district="South Delhi",
                city="New Delhi",
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()

            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            donor_user = User(name="Rahul Sharma", email="rahul@donor.org", role="DONOR")
            donor_user.set_password("DonorPass123!")
            db.session.add(donor_user)
            db.session.flush()

            donor_prof = DonorProfile(
                user_id=donor_user.id,
                declared_blood_group="B+",
                state="Delhi",
                district="South Delhi",
                city="New Delhi",
                availability_status=True,
                verification_status="APPROVED"
            )
            db.session.add(donor_prof)

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp.id,
                blood_group="B+",
                component_type="Whole Blood",
                units_required=1,
                urgency_level="CRITICAL",
                location="ICU Emergency",
                state="Delhi",
                district="South Delhi",
                city="New Delhi",
                contact_phone="+91 11 4455 6677",
                verification_status="VERIFIED",
                request_status="OPEN"
            )
            db.session.add(req)
            db.session.commit()

            req_id = req.id
            donor_id = donor_user.id

        # Hospital logs in
        client.post('/auth/login', data={'email': 'admin@fortis.org', 'password': 'FortisPass123!'}, follow_redirects=True)

        # 1. Hospital sends invitation to matched donor
        res_inv = client.post(f'/hospital/request/{req_id}/invite-donor/{donor_id}', follow_redirects=True)
        assert res_inv.status_code == 200
        assert b"invitation successfully dispatched" in res_inv.data

        # Verify DB invitation record
        with app.app_context():
            inv = DonorInvitation.query.filter_by(blood_request_id=req_id, donor_id=donor_id).first()
            assert inv is not None
            assert inv.status == 'SENT'
            inv_id = inv.id

        # 2. Duplicate Invitation Prevention: Second invitation is rejected cleanly
        res_dup_inv = client.post(f'/hospital/request/{req_id}/invite-donor/{donor_id}', follow_redirects=True)
        assert res_dup_inv.status_code == 200
        assert b"already been dispatched" in res_dup_inv.data

        # 3. Donor accepts invitation
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'rahul@donor.org', 'password': 'DonorPass123!'}, follow_redirects=True)

        res_acc = client.post(f'/donor/invitation/{inv_id}/respond', data={'action': 'ACCEPT'}, follow_redirects=True)
        assert res_acc.status_code == 200
        assert b"accepted the donation invitation" in res_acc.data

        with app.app_context():
            inv = db.session.get(DonorInvitation, inv_id)
            assert inv.status == 'ACCEPTED'
            resp = DonorRequestResponse.query.filter_by(blood_request_id=req_id, donor_id=donor_id).first()
            assert resp is not None
            assert resp.response_status == 'CONFIRMED'
            resp_id = resp.id

        # 4. Hospital updates response status to CONFIRMED
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'admin@fortis.org', 'password': 'FortisPass123!'}, follow_redirects=True)

        res_status = client.post(f'/hospital/response/{resp_id}/status', data={'response_status': 'CONFIRMED'}, follow_redirects=True)
        assert res_status.status_code == 200
        assert b"Donor response status updated to CONFIRMED" in res_status.data

        with app.app_context():
            resp = db.session.get(DonorRequestResponse, resp_id)
            assert resp.response_status == 'CONFIRMED'

    # =========================================================================
    # FEATURE 2.G: IN-APP HOSPITAL-DONOR MESSAGE CENTER & SECURITY
    # =========================================================================
    def test_in_app_messaging_and_authorization(self, app, client):
        """In-app hospital-donor messaging enforces IDOR protection and reporting."""
        with app.app_context():
            hosp_user = User(name="Dr. Coordinator", email="coord@hosp.org", role="HOSPITAL")
            hosp_user.set_password("Pass123!")
            db.session.add(hosp_user)
            db.session.flush()

            hosp = Organization(
                organization_name="Community Hospital",
                organization_type="HOSPITAL",
                registration_reference="COMM-01",
                address="MG Road",
                contact_phone="+91 484 234 5678",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                verification_status="VERIFIED"
            )
            db.session.add(hosp)
            db.session.flush()

            db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

            donor_user = User(name="Sita Donor", email="sita@donor.org", role="DONOR")
            donor_user.set_password("Pass123!")
            db.session.add(donor_user)
            db.session.flush()

            donor_prof = DonorProfile(
                user_id=donor_user.id,
                declared_blood_group="AB+",
                state="Kerala",
                district="Ernakulam",
                city="Kochi"
            )
            db.session.add(donor_prof)

            # Unrelated third-party donor
            other_donor = User(name="Intruder Donor", email="intruder@donor.org", role="DONOR")
            other_donor.set_password("Pass123!")
            db.session.add(other_donor)
            db.session.flush()

            other_prof = DonorProfile(
                user_id=other_donor.id,
                declared_blood_group="O-",
                state="Kerala",
                district="Ernakulam",
                city="Kochi"
            )
            db.session.add(other_prof)

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp.id,
                blood_group="AB+",
                component_type="Whole Blood",
                units_required=1,
                urgency_level="HIGH",
                location="Ward 4",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 234 5678",
                verification_status="VERIFIED",
                request_status="OPEN"
            )
            db.session.add(req)
            db.session.commit()

            req_id = req.id
            donor_id = donor_user.id
            other_id = other_donor.id

        # 1. Hospital opens conversation with Sita Donor
        client.post('/auth/login', data={'email': 'coord@hosp.org', 'password': 'Pass123!'}, follow_redirects=True)
        res_open = client.get(f'/communication/start/{req_id}/{donor_id}', follow_redirects=True)
        assert res_open.status_code == 200

        with app.app_context():
            conv = Conversation.query.filter_by(blood_request_id=req_id, donor_id=donor_id).first()
            assert conv is not None
            conv_id = conv.id

        # 2. Hospital sends a message
        res_send = client.post(f'/communication/conversation/{conv_id}/send', data={
            'message_body': 'Hello Sita, could you come in for blood donation at 10 AM?'
        }, follow_redirects=True)
        assert res_send.status_code == 200

        with app.app_context():
            msg = Message.query.filter_by(conversation_id=conv_id).first()
            assert msg is not None
            assert "10 AM" in msg.message_body
            msg_id = msg.id

        # 3. IDOR CHECK: Unrelated third-party donor attempts to view conversation
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'intruder@donor.org', 'password': 'Pass123!'}, follow_redirects=True)
        res_view_forbidden = client.get(f'/communication/conversation/{conv_id}')
        assert res_view_forbidden.status_code == 403, "Unrelated user must be blocked with 403 Forbidden!"

        # Unrelated donor attempts to send message into conversation
        res_send_forbidden = client.post(f'/communication/conversation/{conv_id}/send', data={'message_body': 'Injected message'}, follow_redirects=True)
        assert res_send_forbidden.status_code == 403

        # 4. Legitimate donor logs in, views message, and reports suspicious message
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'sita@donor.org', 'password': 'Pass123!'}, follow_redirects=True)
        res_donor_view = client.get(f'/communication/conversation/{conv_id}')
        assert res_donor_view.status_code == 200
        assert b"Hello Sita" in res_donor_view.data

        # Report message
        res_report = client.post(f'/communication/message/{msg_id}/report', data={'reason': 'Inappropriate coordination'}, follow_redirects=True)
        assert res_report.status_code == 200
        assert b"reported for administrative safety review" in res_report.data

        with app.app_context():
            reported_msg = db.session.get(Message, msg_id)
            assert reported_msg.is_reported is True

    # =========================================================================
    # FEATURE 3: ADMINISTRATIVE VERIFICATION CENTER & AUDITING
    # =========================================================================
    def test_admin_verification_center_and_document_security(self, app, client):
        """Admin verification center supports approval, rejection with reasons, suspension, and secure documents."""
        with app.app_context():
            admin = User(name="System Admin", email="admin@bloodlink.gov.in", role="ADMIN")
            admin.set_password("SuperAdmin123!")
            db.session.add(admin)

            pending_hosp = Organization(
                organization_name="New City Clinic",
                organization_type="HOSPITAL",
                registration_reference="CLINIC-999",
                address="Anna Salai",
                contact_phone="+91 44 2855 1122",
                state="Tamil Nadu",
                district="Chennai",
                city="Chennai",
                verification_status="PENDING"
            )
            db.session.add(pending_hosp)
            db.session.flush()

            # Create a sample verification document in private directory
            secure_dir = app.config.get('SECURE_DOCUMENTS_DIR')
            os.makedirs(secure_dir, exist_ok=True)
            doc_filename = f"test_license_{pending_hosp.id}.pdf"
            doc_path = os.path.join(secure_dir, doc_filename)
            with open(doc_path, 'wb') as f:
                f.write(b"%PDF-1.4 Mock Clinical License Content")

            app_rec = VerificationApplication(
                user_id=admin.id,
                organization_id=pending_hosp.id,
                verification_type="HOSPITAL",
                verification_status="PENDING_VERIFICATION"
            )
            db.session.add(app_rec)
            db.session.flush()

            ver_doc = VerificationDocument(
                verification_application_id=app_rec.id,
                document_type="CLINICAL_LICENSE",
                private_storage_reference=doc_filename
            )
            db.session.add(ver_doc)
            db.session.commit()

            org_id = pending_hosp.id
            doc_id = ver_doc.id

        # 1. Admin logs in and views Verification Center
        client.post('/auth/login', data={'email': 'admin@bloodlink.gov.in', 'password': 'SuperAdmin123!'}, follow_redirects=True)
        res_ver_dash = client.get('/admin/verifications?tab=hospitals')
        assert res_ver_dash.status_code == 200
        assert b"Registration Verification Center" in res_ver_dash.data
        assert b"New City Clinic" in res_ver_dash.data

        # 2. View protected document from secure directory
        res_doc = client.get(f'/admin/verifications/document/{doc_id}/view')
        assert res_doc.status_code == 200
        assert res_doc.mimetype == "application/pdf"
        assert b"%PDF-1.4 Mock Clinical License Content" in res_doc.data

        # 3. Security Check: Non-admin cannot access protected documents
        client.get('/auth/logout')
        res_doc_unauth = client.get(f'/admin/verifications/document/{doc_id}/view', follow_redirects=False)
        assert res_doc_unauth.status_code in [302, 403, 401]

        # 4. Admin approves organization
        client.post('/auth/login', data={'email': 'admin@bloodlink.gov.in', 'password': 'SuperAdmin123!'}, follow_redirects=True)
        res_appr = client.post(f'/admin/verifications/organization/{org_id}/approve', data={
            'review_method': 'MANUAL_DOCUMENT_REVIEW'
        }, follow_redirects=True)
        assert res_appr.status_code == 200
        assert b"has been successfully APPROVED" in res_appr.data

        with app.app_context():
            org = db.session.get(Organization, org_id)
            assert org.verification_status in ('VERIFIED', 'APPROVED')
            assert org.is_verified is True

        # 5. Admin suspends organization
        res_susp = client.post(f'/admin/verifications/organization/{org_id}/suspend', data={
            'reason': 'Routine clinical audit pending response'
        }, follow_redirects=True)
        assert res_susp.status_code == 200
        assert b"has been SUSPENDED" in res_susp.data

        with app.app_context():
            org = db.session.get(Organization, org_id)
            assert org.verification_status == 'SUSPENDED'
            assert org.is_verified is False

        # 6. Admin restores organization
        res_rest = client.post(f'/admin/verifications/organization/{org_id}/restore', follow_redirects=True)
        assert res_rest.status_code == 200
        assert b"restored to APPROVED standing" in res_rest.data

        with app.app_context():
            org = db.session.get(Organization, org_id)
            assert org.verification_status in ('VERIFIED', 'APPROVED')
            assert org.is_verified is True
