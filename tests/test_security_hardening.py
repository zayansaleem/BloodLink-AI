import pytest
from datetime import datetime, timezone, timedelta
import pyotp
from app import create_app
from app.extensions import db
from app.models.user import User, PasswordResetToken
from app.models.organization import Organization, OrganizationMembership
from app.models.audit import AuditLog
from app.models.donor import DonorProfile


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


class TestSecurityHardening:
    """Comprehensive test suite verifying BloodLink AI responsive, authentication, and admin hardening."""

    # --------------------------------------------------------------------------
    # 1. Responsive Viewports & Navigation
    # --------------------------------------------------------------------------
    def test_mobile_viewport_and_offcanvas_navigation(self, client):
        """Verify presence of responsive viewport meta tag and offcanvas mobile menu."""
        response = client.get('/')
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        # Responsive viewport meta tag
        assert '<meta name="viewport" content="width=device-width, initial-scale=1.0' in html

        # Offcanvas mobile navigation structure
        assert 'navbarOffcanvas' in html
        assert 'navbar-toggler' in html
        assert 'offcanvas-end' in html

    def test_dedicated_login_and_register_routes(self, client):
        """Verify dedicated top-level /login and /register route aliases work alongside /auth/."""
        resp_login_alias = client.get('/login')
        assert resp_login_alias.status_code == 200
        assert 'Sign In' in resp_login_alias.get_data(as_text=True)

        resp_register_alias = client.get('/register')
        assert resp_register_alias.status_code == 200
        assert 'Register' in resp_register_alias.get_data(as_text=True)

        resp_auth_login = client.get('/auth/login')
        assert resp_auth_login.status_code == 200

        resp_auth_register = client.get('/auth/register')
        assert resp_auth_register.status_code == 200

    # --------------------------------------------------------------------------
    # 2. HTTP Security Headers
    # --------------------------------------------------------------------------
    def test_security_headers_emitted_on_responses(self, client):
        """Verify essential HTTP security headers are applied to HTTP responses."""
        response = client.get('/')
        assert response.status_code == 200

        assert response.headers.get('X-Content-Type-Options') == 'nosniff'
        assert response.headers.get('X-Frame-Options') == 'DENY'
        assert response.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'
        assert 'Content-Security-Policy' in response.headers
        csp = response.headers.get('Content-Security-Policy')
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    # --------------------------------------------------------------------------
    # 3. Generic Authentication Errors & Session Fixation Protection
    # --------------------------------------------------------------------------
    def test_generic_login_errors_prevent_account_enumeration(self, app, client):
        """Verify failed logins display identical generic error messages for nonexistent or bad passwords."""
        # Non-existent user
        resp_nonexistent = client.post('/auth/login', data={
            'email': 'nobody@bloodlink.org',
            'password': 'AnyPassword123'
        }, follow_redirects=True)
        text_nonexistent = resp_nonexistent.get_data(as_text=True)
        assert "Unable to sign in with the supplied credentials." in text_nonexistent

        # Existing user with wrong password
        user = User(name="Alice Donor", email="alice@bloodlink.org", role="DONOR")
        user.set_password("CorrectPassword123")
        db.session.add(user)
        db.session.commit()

        resp_wrong_pw = client.post('/auth/login', data={
            'email': 'alice@bloodlink.org',
            'password': 'WrongPassword999'
        }, follow_redirects=True)
        text_wrong_pw = resp_wrong_pw.get_data(as_text=True)
        assert "Unable to sign in with the supplied credentials." in text_wrong_pw

    # --------------------------------------------------------------------------
    # 4. Account Lockout & Brute-Force Defense
    # --------------------------------------------------------------------------
    def test_account_temporary_lockout_after_failed_attempts(self, app, client):
        """Verify account locks temporarily after 5 failed login attempts and resets on success."""
        user = User(name="Bob Test", email="bob@bloodlink.org", role="DONOR")
        user.set_password("Secret12345")
        db.session.add(user)
        db.session.commit()

        # Submit 5 incorrect login attempts
        for i in range(5):
            client.post('/auth/login', data={'email': 'bob@bloodlink.org', 'password': f'badpw{i}'})

        # Reload user from DB
        db.session.refresh(user)
        assert user.failed_login_attempts == 5
        assert user.is_temporarily_locked() is True
        assert user.locked_until is not None

        # 6th attempt with correct password should be rejected due to active lockout
        locked_resp = client.post('/auth/login', data={'email': 'bob@bloodlink.org', 'password': 'Secret12345'}, follow_redirects=True)
        # Requirement 2 mandates generic error to avoid account enumeration
        assert "Unable to sign in with the supplied credentials." in locked_resp.get_data(as_text=True)

        # Clear lockout manually (simulating expiry or admin unlock)
        user.record_successful_login()
        db.session.commit()
        assert user.failed_login_attempts == 0
        assert user.is_temporarily_locked() is False

        # Now correct login succeeds
        good_resp = client.post('/auth/login', data={'email': 'bob@bloodlink.org', 'password': 'Secret12345'}, follow_redirects=True)
        assert f"Welcome back, {user.name}!" in good_resp.get_data(as_text=True)

    def test_flask_limiter_rate_limiting_triggers_429(self):
        """Verify Flask-Limiter enforces rate limiting and triggers HTTP 429 with custom error page."""
        test_app = create_app('development')
        test_app.config['LOGIN_RATE_LIMIT'] = '2 per minute'
        test_app.config['WTF_CSRF_ENABLED'] = False
        with test_app.app_context():
            db.create_all()
            with test_app.test_client() as tc:
                # 2 allowed requests
                resp1 = tc.post('/auth/login', data={'email': 'rate@bloodlink.org', 'password': 'pw'})
                resp2 = tc.post('/auth/login', data={'email': 'rate@bloodlink.org', 'password': 'pw'})
                assert resp1.status_code == 200
                assert resp2.status_code == 200

                # 3rd request throttled with HTTP 429
                resp3 = tc.post('/auth/login', data={'email': 'rate@bloodlink.org', 'password': 'pw'})
                assert resp3.status_code == 429
                assert "Too Many Requests" in resp3.get_data(as_text=True)
                assert "429" in resp3.get_data(as_text=True)

    # --------------------------------------------------------------------------
    # 5. Cryptographic Password Reset Tokens
    # --------------------------------------------------------------------------
    def test_password_reset_token_lifecycle(self, app):
        """Verify tokens are hashed at rest, single-use, and expire appropriately."""
        user = User(name="Carol Reset", email="carol@bloodlink.org", role="DONOR")
        user.set_password("OldPassword123")
        db.session.add(user)
        db.session.commit()

        # Generate token
        raw_token = PasswordResetToken.create_token_for_user(user_id=user.id, expires_minutes=15)
        token_record = PasswordResetToken.query.filter_by(
            token_hash=PasswordResetToken.hash_token(raw_token)
        ).first()

        # Ensure token is hashed in DB, never plaintext
        assert token_record is not None
        assert token_record.token_hash != raw_token
        assert len(token_record.token_hash) == 64  # SHA-256 hex length

        # Successful verification
        verified_token = PasswordResetToken.verify_raw_token(raw_token)
        assert verified_token is not None
        assert verified_token.user_id == user.id

        # Mark token as used
        verified_token.mark_used()

        # Re-verification must fail (single-use)
        reused_token = PasswordResetToken.verify_raw_token(raw_token)
        assert reused_token is None

        # Test expiration
        raw_token_exp = PasswordResetToken.create_token_for_user(user_id=user.id, expires_minutes=-10)
        expired_token = PasswordResetToken.verify_raw_token(raw_token_exp)
        assert expired_token is None

    # --------------------------------------------------------------------------
    # 6. Public Registration Security Boundaries
    # --------------------------------------------------------------------------
    def test_registration_prevents_admin_role_escalation(self, app, client):
        """Verify public registration cannot create an ADMIN account."""
        resp = client.post('/auth/register', data={
            'name': 'Hacker Wannabe',
            'email': 'hacker@bloodlink.org',
            'password': 'StrongPassword123',
            'confirm_password': 'StrongPassword123',
            'role': 'ADMIN'
        }, follow_redirects=True)

        user = User.query.filter_by(email='hacker@bloodlink.org').first()
        if user:
            assert user.role != 'ADMIN'

    def test_registration_enforces_minimum_password_length(self, app, client):
        """Verify passwords under 8 characters are rejected."""
        resp = client.post('/auth/register', data={
            'name': 'Short Password',
            'email': 'short@bloodlink.org',
            'blood_group': 'O+',
            'state': 'Maharashtra',
            'district': 'Mumbai',
            'password': '12345',
            'confirm_password': '12345',
            'role': 'DONOR'
        }, follow_redirects=True)

        assert "Password must be at least 8 characters" in resp.get_data(as_text=True)
        assert User.query.filter_by(email='short@bloodlink.org').first() is None

    # --------------------------------------------------------------------------
    # 7. Open-Redirect Prevention
    # --------------------------------------------------------------------------
    def test_open_redirect_defense(self, app, client):
        """Verify login next parameter disallows malicious external domains."""
        user = User(name="Dave Donor", email="dave@bloodlink.org", role="DONOR")
        user.set_password("ValidPassword123")
        db.session.add(user)
        db.session.commit()

        resp = client.post('/auth/login?next=http://malicious-external-phishing.com', data={
            'email': 'dave@bloodlink.org',
            'password': 'ValidPassword123'
        })
        # Must redirect to donor dashboard, NOT to external phishing site
        assert resp.status_code == 302
        assert 'malicious-external-phishing.com' not in resp.location
        assert '/donor/dashboard' in resp.location

    # --------------------------------------------------------------------------
    # 8. Pending Facility Verification Enforcement
    # --------------------------------------------------------------------------
    def test_pending_facility_redirected_to_verification_status(self, app, client):
        """Verify unverified hospital accounts are redirected to /auth/verification-status on trusted ops."""
        hosp_user = User(name="Hosp Admin", email="hosp@bloodlink.org", role="HOSPITAL")
        hosp_user.set_password("HospitalPass123")
        db.session.add(hosp_user)
        db.session.commit()

        org = Organization(
            organization_name="City Hospital",
            organization_type="HOSPITAL",
            address="Center St",
            contact_phone="1234567890",
            verification_status="PENDING"
        )
        db.session.add(org)
        db.session.commit()

        membership = OrganizationMembership(user_id=hosp_user.id, organization_id=org.id, membership_role="ADMIN")
        db.session.add(membership)
        db.session.commit()

        # Log in as hospital rep -> routed directly to verification-status desk
        login_resp = client.post('/auth/login', data={'email': 'hosp@bloodlink.org', 'password': 'HospitalPass123'}, follow_redirects=False)
        assert login_resp.status_code == 302
        assert '/auth/verification-status' in login_resp.location

        # Direct view of verification status
        status_resp = client.get('/auth/verification-status')
        assert status_resp.status_code == 200
        assert 'Accreditation Audit in Progress' in status_resp.get_data(as_text=True)

        # Attempt to access trusted operational action: create request -> redirected back with restriction
        resp = client.get('/hospital/request/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/hospital/dashboard' in resp.location

    # --------------------------------------------------------------------------
    # 9. Role-Based Access Control (RBAC) Isolation
    # --------------------------------------------------------------------------
    def test_rbac_donor_cannot_access_admin_dashboard(self, app, client):
        """Verify standard DONOR cannot access /admin/dashboard or /admin/users."""
        donor = User(name="Eve Donor", email="eve@bloodlink.org", role="DONOR")
        donor.set_password("EvePass123")
        db.session.add(donor)
        db.session.commit()

        client.post('/auth/login', data={'email': 'eve@bloodlink.org', 'password': 'EvePass123'})

        resp_admin = client.get('/admin/dashboard')
        assert resp_admin.status_code == 403

        resp_users = client.get('/admin/users')
        assert resp_users.status_code == 403

    # --------------------------------------------------------------------------
    # 10. Admin MFA (TOTP)
    # --------------------------------------------------------------------------
    def test_totp_mfa_generation_and_verification(self, app):
        """Verify TOTP secret generation and valid code validation."""
        admin = User(name="Root Admin", email="root@bloodlink.org", role="ADMIN")
        admin.set_password("AdminSecurePass123")
        db.session.add(admin)
        db.session.commit()

        secret = admin.generate_mfa_secret()
        assert secret is not None
        assert len(secret) == 32

        totp = pyotp.TOTP(secret)
        current_token = totp.now()

        assert admin.verify_totp(current_token) is True
        assert admin.verify_totp('000000') is False

    # --------------------------------------------------------------------------
    # 11. Admin Privileged Operations: Suspension & Unlock
    # --------------------------------------------------------------------------
    def test_admin_can_suspend_and_unlock_accounts(self, app, client):
        """Verify admin can suspend a user, reactivate, and unlock brute-force restricted accounts."""
        admin = User(name="Super Admin", email="superadmin@bloodlink.org", role="ADMIN")
        admin.set_password("SuperAdminPass123")
        db.session.add(admin)

        target_user = User(name="Suspicious User", email="bad@bloodlink.org", role="DONOR")
        target_user.set_password("TargetPass123")
        target_user.failed_login_attempts = 5
        target_user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.session.add(target_user)
        db.session.commit()

        # Log in as admin
        client.post('/auth/login', data={'email': 'superadmin@bloodlink.org', 'password': 'SuperAdminPass123'})

        # Admin unlocks target account
        resp_unlock = client.post(f'/admin/users/{target_user.id}/unlock', data={'reason': 'Identity verified via call'}, follow_redirects=True)
        assert resp_unlock.status_code == 200

        db.session.refresh(target_user)
        assert target_user.is_temporarily_locked() is False
        assert target_user.failed_login_attempts == 0

        # Verify audit log was created for unlock
        unlock_log = AuditLog.query.filter_by(action='UNLOCK_ACCOUNT', entity_id=target_user.id).first()
        assert unlock_log is not None
        assert unlock_log.actor_id == admin.id
        assert 'Identity verified' in unlock_log.details

        # Admin suspends user
        resp_suspend = client.post(f'/admin/users/{target_user.id}/toggle-status', data={'reason': 'Fraud investigation'}, follow_redirects=True)
        assert resp_suspend.status_code == 200

        db.session.refresh(target_user)
        assert target_user.is_active is False

        # Suspended user cannot log in (generic error returned)
        client.get('/auth/logout')
        resp_blocked = client.post('/auth/login', data={'email': 'bad@bloodlink.org', 'password': 'TargetPass123'}, follow_redirects=True)
        assert "Unable to sign in with the supplied credentials." in resp_blocked.get_data(as_text=True)

    def test_admin_cannot_suspend_self(self, app, client):
        """Verify an admin cannot accidentally or maliciously suspend their own account."""
        admin = User(name="Self Admin", email="selfadmin@bloodlink.org", role="ADMIN")
        admin.set_password("SelfAdminPass123")
        db.session.add(admin)
        db.session.commit()

        client.post('/auth/login', data={'email': 'selfadmin@bloodlink.org', 'password': 'SelfAdminPass123'})

        resp = client.post(f'/admin/users/{admin.id}/toggle-status', data={'reason': 'Testing self-suspension'}, follow_redirects=True)
        assert "cannot suspend your own administrator account" in resp.get_data(as_text=True)

        db.session.refresh(admin)
        assert admin.is_active is True
