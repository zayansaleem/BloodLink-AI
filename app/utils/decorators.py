from functools import wraps
from flask import abort, flash, redirect, url_for, session, current_app
from flask_login import current_user, logout_user


def role_required(*roles):
    """Ensure the authenticated user possesses one of the allowed system roles and is active."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if not current_user.is_active:
                logout_user()
                flash("Your account has been deactivated. Please contact support.", "danger")
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                flash("Access denied: You do not possess the required permissions for this section.", "danger")
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """Restrict access strictly to Platform Administrators with server-verified role and MFA checks."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_active:
            logout_user()
            flash("Account deactivated.", "danger")
            return redirect(url_for('auth.login'))
        if current_user.role != 'ADMIN':
            abort(403)

        # Enforce MFA in production configuration or when enrolled
        require_mfa = current_app.config.get('REQUIRE_ADMIN_MFA', False)
        if (require_mfa or current_user.mfa_enabled) and not session.get('admin_mfa_verified'):
            session['pending_admin_mfa_user_id'] = current_user.id
            flash("Administrative console requires verified multi-factor authentication.", "warning")
            return redirect(url_for('auth.verify_mfa'))

        return f(*args, **kwargs)
    return decorated_function


def verified_org_required(f):
    """Ensure organization users (Hospital or Blood Bank) have an approved verification status."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

        # Admins bypass facility approval checks
        if current_user.role == 'ADMIN':
            return f(*args, **kwargs)

        org = current_user.organization
        if not org or not org.is_verified:
            flash(
                "Access restricted: Your organization account is pending administrator verification. "
                "Trusted operations (issuing trusted requests, modifying inventory, verifying donations) "
                "require formal approval.",
                "warning"
            )
            endpoint = 'hospital.dashboard' if current_user.role == 'HOSPITAL' else 'blood_bank.dashboard'
            return redirect(url_for(endpoint))

        return f(*args, **kwargs)
    return decorated_function
