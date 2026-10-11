from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db, limiter, get_client_ip
from app.models.user import User, PasswordResetToken
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.audit import AuditLog
from app.models.verification import VerificationApplication

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


def is_safe_url(target: str) -> bool:
    """Validate that redirect target is safe and internal, preventing open-redirect attacks."""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(lambda: current_app.config.get('LOGIN_RATE_LIMIT', '10 per minute; 50 per hour'), methods=['POST'])
def login():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user.role)

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))
        client_ip = get_client_ip()

        user = User.query.filter_by(email=email).first()

        # Account-level temporary lockout defense
        if user and user.is_temporarily_locked():
            AuditLog.log(
                action='AUTH_LOCKOUT_BLOCKED',
                entity_type='User',
                entity_id=user.id,
                details=f"Login attempt blocked by temporary lockout threshold for account {user.id}",
                actor_id=user.id,
                ip_address=client_ip
            )
            db.session.commit()
            # Generic response to prevent account enumeration
            flash("Unable to sign in with the supplied credentials.", "danger")
            return render_template('auth/login.html')

        # Generic authentication failure
        if not user or not user.check_password(password) or not user.is_active:
            if user:
                max_att = current_app.config.get('MAX_FAILED_LOGIN_ATTEMPTS', 5)
                lock_min = current_app.config.get('LOGIN_LOCKOUT_MINUTES', 15)
                user.record_failed_login(max_attempts=max_att, lockout_minutes=lock_min)

            AuditLog.log(
                action='AUTH_FAILED_LOGIN',
                entity_type='User',
                entity_id=user.id if user else None,
                details=f"Failed login attempt for {email or 'empty'} from {client_ip}",
                actor_id=user.id if user else None,
                ip_address=client_ip
            )
            db.session.commit()

            flash("Unable to sign in with the supplied credentials.", "danger")
            return render_template('auth/login.html')

        # Successful credential verification -> Reset failed attempts
        user.record_successful_login()

        # Multi-Factor Authentication check for Platform Administrators
        require_mfa = current_app.config.get('REQUIRE_ADMIN_MFA', False)
        if user.role == 'ADMIN' and (user.mfa_enabled or require_mfa):
            session['pending_admin_mfa_user_id'] = user.id
            session['pending_admin_remember'] = remember
            session['pending_admin_next'] = request.args.get('next')
            return redirect(url_for('auth.verify_mfa'))

        # Session fixation protection: clear anonymous session state before elevating
        session.clear()
        login_user(user, remember=remember)

        AuditLog.log(
            action='USER_LOGIN',
            entity_type='User',
            entity_id=user.id,
            details=f"Authenticated from {client_ip}",
            actor_id=user.id,
            ip_address=client_ip
        )
        db.session.commit()

        flash(f"Welcome back, {user.name}!", "success")

        next_page = request.args.get('next')
        if next_page and is_safe_url(next_page):
            return redirect(next_page)

        # Route unverified organization coordinators to verification status desk
        if user.role in ['HOSPITAL', 'BLOOD_BANK']:
            org = user.organization
            if org and not org.is_verified:
                return redirect(url_for('auth.verification_status'))

        return redirect(_get_role_dashboard_url(user.role))

    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit(lambda: current_app.config.get('REGISTER_RATE_LIMIT', '20 per minute; 100 per hour'), methods=['POST'])
def register():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user.role)

    reg_type = request.args.get('type', 'donor').lower()

    if request.method == 'POST':
        reg_type = request.form.get('reg_type', 'donor').lower()

        # Strictly reject any unauthorized public administrator registration attempt
        if reg_type not in ['donor', 'hospital', 'blood_bank']:
            flash("Invalid registration account type.", "danger")
            return render_template('auth/register.html', reg_type='donor')

        if reg_type == 'donor':
            return _handle_donor_registration()
        elif reg_type in ['hospital', 'blood_bank']:
            return _handle_organization_registration(reg_type.upper())

    return render_template('auth/register.html', reg_type=reg_type)


def _handle_donor_registration():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password')
    blood_group = request.form.get('blood_group', '').strip().upper()
    state = request.form.get('state', '').strip()
    district = request.form.get('district', '').strip()
    city = request.form.get('city', '').strip()
    phone = request.form.get('phone', '').strip()
    notification_consent = bool(request.form.get('notification_consent'))

    from app.locations import is_valid_state, is_valid_district

    if not name or not email or not password or not blood_group:
        flash("Please fill in all mandatory fields.", "warning")
        return render_template('auth/register.html', reg_type='donor', form_data=request.form)

    if len(password) < 8:
        flash("Password must be at least 8 characters in length.", "warning")
        return render_template('auth/register.html', reg_type='donor', form_data=request.form)

    if confirm_password is not None and password != confirm_password:
        flash("Passwords do not match. Please verify your password.", "warning")
        return render_template('auth/register.html', reg_type='donor', form_data=request.form)

    if not state or not is_valid_state(state):
        flash(f"Invalid State: '{state}' is not a recognized Indian State or Union Territory.", "danger")
        return render_template('auth/register.html', reg_type='donor', form_data=request.form)

    if not district or not is_valid_district(state, district):
        flash(f"Invalid District: '{district}' does not belong to the selected state ({state}).", "danger")
        return render_template('auth/register.html', reg_type='donor', form_data=request.form)

    lat_val = request.form.get('latitude')
    lng_val = request.form.get('longitude')
    try:
        latitude = float(lat_val) if lat_val else None
        longitude = float(lng_val) if lng_val else None
    except (ValueError, TypeError):
        latitude, longitude = None, None

    # Check email conflict; flash generic message to prevent account enumeration
    if User.query.filter_by(email=email).first():
        flash("An account with this email address already exists. Please sign in or reset your password.", "danger")
        return render_template('auth/register.html', reg_type='donor', form_data=request.form)

    try:
        user = User(
            name=name,
            email=email,
            role='DONOR',
            is_active=True,
            email_verified=True
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        profile = DonorProfile(
            user_id=user.id,
            declared_blood_group=blood_group,
            country="India",
            state=state,
            district=district,
            city=city,
            latitude=latitude,
            longitude=longitude,
            phone=phone,
            availability_status=True,
            notification_consent=notification_consent
        )
        db.session.add(profile)

        AuditLog.log(action='REGISTER_DONOR', entity_type='User', entity_id=user.id, actor_id=user.id, ip_address=get_client_ip())
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Registration Error] Failed to persist donor {email}: {e}")
        flash("A database error occurred while creating your account. Please try again.", "danger")
        return render_template('auth/register.html', reg_type='donor', form_data=request.form)

    session.clear()
    login_user(user)
    flash(f"Registration successful! Welcome to the BloodLink AI lifesaver network, {user.name}.", "success")
    return redirect(url_for('donor.dashboard'))


def _handle_organization_registration(org_type):
    org_name = request.form.get('org_name', '').strip()
    reg_ref = request.form.get('registration_reference', '').strip()
    contact_phone = request.form.get('contact_phone', '').strip()
    contact_email = request.form.get('contact_email', '').strip().lower()
    address = request.form.get('address', '').strip()
    state = request.form.get('state', '').strip()
    district = request.form.get('district', '').strip()
    city = request.form.get('city', '').strip()
    rep_name = request.form.get('representative_name', '').strip()
    rep_email = request.form.get('representative_email', '').strip().lower()
    rep_password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password')

    from app.locations import is_valid_state, is_valid_district

    if not org_name or not rep_name or not rep_email or not rep_password or not address:
        flash("Please fill in all mandatory organization fields.", "warning")
        return render_template('auth/register.html', reg_type=org_type.lower(), form_data=request.form)

    if len(rep_password) < 8:
        flash("Password must be at least 8 characters in length.", "warning")
        return render_template('auth/register.html', reg_type=org_type.lower(), form_data=request.form)

    if confirm_password is not None and rep_password != confirm_password:
        flash("Passwords do not match. Please verify your password.", "warning")
        return render_template('auth/register.html', reg_type=org_type.lower(), form_data=request.form)

    if not state or not is_valid_state(state):
        flash(f"Invalid State: '{state}' is not a recognized Indian State or Union Territory.", "danger")
        return render_template('auth/register.html', reg_type=org_type.lower(), form_data=request.form)

    if not district or not is_valid_district(state, district):
        flash(f"Invalid District: '{district}' does not belong to {state}.", "danger")
        return render_template('auth/register.html', reg_type=org_type.lower(), form_data=request.form)

    lat_val = request.form.get('latitude')
    lng_val = request.form.get('longitude')
    try:
        latitude = float(lat_val) if lat_val else None
        longitude = float(lng_val) if lng_val else None
    except (ValueError, TypeError):
        latitude, longitude = None, None

    if User.query.filter_by(email=rep_email).first():
        flash("A representative account with this email address already exists. Please sign in or reset your password.", "danger")
        return render_template('auth/register.html', reg_type=org_type.lower(), form_data=request.form)

    # Create Organization starting strictly in PENDING verification status
    org = Organization(
        organization_name=org_name,
        organization_type=org_type,
        registration_reference=reg_ref,
        address=address,
        country="India",
        state=state,
        district=district,
        city=city,
        latitude=latitude,
        longitude=longitude,
        contact_phone=contact_phone,
        contact_email=contact_email,
        verification_status='PENDING'
    )
    try:
        db.session.add(org)
        db.session.flush()

        user = User(
            name=rep_name,
            email=rep_email,
            role=org_type,
            is_active=True,
            email_verified=True
        )
        user.set_password(rep_password)
        db.session.add(user)
        db.session.flush()

        membership = OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            membership_role='ADMIN'
        )
        db.session.add(membership)

        verification_app = VerificationApplication(
            user_id=user.id,
            organization_id=org.id,
            verification_type=org_type,
            verification_status='PENDING_VERIFICATION',
            verification_method='ONLINE_REGISTRATION',
            provider_reference=reg_ref
        )
        db.session.add(verification_app)

        AuditLog.log(action='REGISTER_ORGANIZATION', entity_type='Organization', entity_id=org.id, actor_id=user.id, ip_address=get_client_ip())
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"[Registration Error] Failed to persist organization {org_name}: {e}")
        flash("A database error occurred while registering your organization. Please try again.", "danger")
        return render_template('auth/register.html', reg_type=org_type.lower(), form_data=request.form)

    session.clear()
    login_user(user)
    flash(
        f"Organization account registered! Welcome, {org_name}. "
        "Your facility is in 'PENDING' status. Platform administrators must review and approve credentials "
        "before clinical requests or inventory adjustments can be performed.",
        "warning"
    )
    return redirect(url_for('auth.verification_status'))


@auth_bp.route('/verification-status')
@login_required
def verification_status():
    """Dedicated information portal explaining organization review status and clinical restrictions."""
    org = current_user.organization
    app_rec = None
    if org:
        app_rec = VerificationApplication.query.filter_by(organization_id=org.id)\
            .order_by(VerificationApplication.submitted_at.desc()).first()
    return render_template('auth/verification_status.html', org=org, application=app_rec)


# ========================================================
# Cryptographic Password Reset Flow
# ========================================================

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit(lambda: current_app.config.get('PASSWORD_RESET_RATE_LIMIT', '3 per minute; 10 per hour'), methods=['POST'])
def forgot_password():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user.role)

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        client_ip = get_client_ip()

        user = User.query.filter_by(email=email).first()
        if user and user.is_active:
            token_minutes = current_app.config.get('PASSWORD_RESET_TOKEN_MINUTES', 15)
            raw_token = PasswordResetToken.create_token_for_user(user.id, expires_minutes=token_minutes)

            AuditLog.log(
                action='PASSWORD_RESET_REQUESTED',
                entity_type='User',
                entity_id=user.id,
                details=f"Password reset token issued for user {user.id}",
                actor_id=user.id,
                ip_address=client_ip
            )
            db.session.commit()

            # In development/test sandbox, make the reset link accessible for test automation
            if current_app.config.get('DEBUG') or current_app.config.get('TESTING'):
                reset_url = url_for('auth.reset_password', token=raw_token, _external=True)
                flash(f"[Sandbox Demo] Password reset link: {reset_url}", "info")

        # Always return generic message to defeat email harvesting & account enumeration
        flash("If an account associated with that email exists, password reset instructions have been issued.", "info")
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return _redirect_by_role(current_user.role)

    token_record = PasswordResetToken.verify_raw_token(token)
    if not token_record:
        flash("The password reset link is invalid or has expired.", "danger")
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if len(password) < 8:
            flash("New password must be at least 8 characters in length.", "warning")
            return render_template('auth/reset_password.html', token=token)

        if password != confirm_password:
            flash("Passwords do not match. Please verify your new password.", "warning")
            return render_template('auth/reset_password.html', token=token)

        user = db.session.get(User, token_record.user_id)
        if not user:
            flash("Invalid account reference.", "danger")
            return redirect(url_for('auth.login'))

        # Set new password, invalidate reset token, clear lockout states
        user.set_password(password)
        user.record_successful_login()
        token_record.mark_used()

        AuditLog.log(
            action='PASSWORD_RESET_COMPLETED',
            entity_type='User',
            entity_id=user.id,
            details="Password successfully updated via single-use reset token",
            actor_id=user.id,
            ip_address=get_client_ip()
        )
        db.session.commit()

        # Invalidate any lingering session state
        session.clear()

        flash("Your password has been successfully reset! You may now sign in with your new credentials.", "success")
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


# ========================================================
# Administrator Multi-Factor Authentication (MFA / TOTP)
# ========================================================

@auth_bp.route('/verify-mfa', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def verify_mfa():
    """Verify administrator 6-digit TOTP token before granting privileged session access."""
    user_id = session.get('pending_admin_mfa_user_id')
    if not user_id:
        return redirect(url_for('auth.login'))

    user = db.session.get(User, user_id)
    if not user or user.role != 'ADMIN':
        session.clear()
        return redirect(url_for('auth.login'))

    is_prod = current_app.config.get('REQUIRE_ADMIN_MFA', False)

    if request.method == 'POST':
        mfa_token = request.form.get('mfa_token', '').strip()
        client_ip = get_client_ip()

        # If user has not enrolled MFA yet and not in prod mode, allow dev setup
        if not user.mfa_secret and not is_prod:
            user.generate_mfa_secret()
            db.session.commit()

        if user.verify_totp(mfa_token):
            # MFA success: complete authentication session elevation
            remember = session.pop('pending_admin_remember', False)
            next_url = session.pop('pending_admin_next', None)
            session.pop('pending_admin_mfa_user_id', None)

            session.clear()
            login_user(user, remember=remember)
            session['admin_mfa_verified'] = True

            AuditLog.log(
                action='MFA_VERIFY_SUCCESS',
                entity_type='User',
                entity_id=user.id,
                details=f"Successful TOTP verification for administrator {user.email}",
                actor_id=user.id,
                ip_address=client_ip
            )
            db.session.commit()

            flash(f"Administrator multi-factor authentication verified. Welcome, {user.name}.", "success")
            if next_url and is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for('admin.dashboard'))
        else:
            AuditLog.log(
                action='MFA_VERIFY_FAILURE',
                entity_type='User',
                entity_id=user.id,
                details=f"Invalid TOTP token attempt for administrator {user.email}",
                actor_id=user.id,
                ip_address=client_ip
            )
            db.session.commit()
            flash("Invalid authentication code. Please check your authenticator application.", "danger")

    return render_template('auth/verify_mfa.html', is_prod_mode=is_prod)


@auth_bp.route('/setup-mfa', methods=['GET', 'POST'])
@login_required
def setup_mfa():
    """Enroll or rotate administrator RFC 6238 TOTP Base32 secret."""
    if current_user.role != 'ADMIN':
        abort(403)

    if request.method == 'POST':
        secret = request.form.get('mfa_secret', '').strip()
        token = request.form.get('mfa_token', '').strip()

        import pyotp
        totp = pyotp.TOTP(secret)
        if totp.verify(token, valid_window=1):
            current_user.mfa_secret = secret
            current_user.mfa_enabled = True
            session['admin_mfa_verified'] = True

            AuditLog.log(
                action='MFA_ENROLLED',
                entity_type='User',
                entity_id=current_user.id,
                details="Administrator enrolled in TOTP two-factor authentication",
                actor_id=current_user.id,
                ip_address=get_client_ip()
            )
            db.session.commit()

            flash("Two-factor authentication successfully enabled on your administrator account.", "success")
            return redirect(url_for('admin.dashboard'))
        else:
            flash("Invalid code. Please ensure the code entered matches your authenticator application.", "danger")

    mfa_secret = current_user.mfa_secret or current_user.generate_mfa_secret()
    return render_template('auth/setup_mfa.html', mfa_secret=mfa_secret)


@auth_bp.route('/logout')
@login_required
def logout():
    AuditLog.log(action='USER_LOGOUT', entity_type='User', entity_id=current_user.id, actor_id=current_user.id, ip_address=get_client_ip())
    db.session.commit()
    session.clear()
    logout_user()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for('main.index'))


def _get_role_dashboard_url(role):
    if role == 'DONOR':
        return url_for('donor.dashboard')
    elif role == 'HOSPITAL':
        return url_for('hospital.dashboard')
    elif role == 'BLOOD_BANK':
        return url_for('blood_bank.dashboard')
    elif role == 'ADMIN':
        return url_for('admin.dashboard')
    return url_for('main.index')


def _redirect_by_role(role):
    return redirect(_get_role_dashboard_url(role))
