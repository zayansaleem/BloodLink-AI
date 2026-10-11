import os
from flask import Flask, render_template
from config import config_by_name
from app.extensions import db, migrate, login_manager, csrf, limiter


def create_app(config_name='default', config_overrides=None):
    """Application factory for BloodLink AI."""
    app = Flask(__name__)
    config_obj = config_by_name.get(config_name, config_by_name['default'])
    app.config.from_object(config_obj)
    if config_overrides:
        app.config.update(config_overrides)

    # Ensure instance directory exists
    instance_dir = os.path.join(app.root_path, '..', 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    secure_docs_dir = os.path.join(instance_dir, 'secure_documents')
    os.makedirs(secure_docs_dir, exist_ok=True)
    app.config['SECURE_DOCUMENTS_DIR'] = secure_docs_dir

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # SQLite Concurrency & Stability: WAL mode & 30-sec busy timeout to avoid locks during DB Browser inspection
    with app.app_context():
        if db.engine.url.drivername.startswith('sqlite'):
            from sqlalchemy import event
            @event.listens_for(db.engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL;")
                    cursor.execute("PRAGMA busy_timeout=30000;")
                    cursor.execute("PRAGMA synchronous=NORMAL;")
                except Exception:
                    pass
                finally:
                    cursor.close()

    # User loader
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register Blueprints
    from app.main.routes import main_bp
    from app.auth.routes import auth_bp
    from app.donor.routes import donor_bp
    from app.hospital.routes import hospital_bp
    from app.blood_bank.routes import blood_bank_bp
    from app.admin.routes import admin_bp
    from app.communication.routes import communication_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(donor_bp)
    app.register_blueprint(hospital_bp)
    app.register_blueprint(blood_bank_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(communication_bp)

    # Global Context Processor
    @app.context_processor
    def inject_global_vars():
        from app.locations import get_all_states, get_all_locations_hierarchy
        return {
            'app_name': 'BloodLink AI',
            'tagline': "Every Drop Matters. Every Second Counts.",
            'all_indian_states': get_all_states(),
            'indian_locations_hierarchy': get_all_locations_hierarchy()
        }

    # Safe lightweight schema auto-upgrade for SQLite/Postgres
    with app.app_context():
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            if 'blood_requests' in tables:
                cols = [c['name'] for c in inspector.get_columns('blood_requests')]
                for col_name in ['country', 'state', 'district', 'city', 'postal_code']:
                    if col_name not in cols:
                        db.session.execute(text(f"ALTER TABLE blood_requests ADD COLUMN {col_name} VARCHAR(64)"))
                for col_name in ['patient_name', 'patient_reference']:
                    if col_name not in cols:
                        db.session.execute(text(f"ALTER TABLE blood_requests ADD COLUMN {col_name} VARCHAR(120)"))
                db.session.commit()
            if 'donor_profiles' in tables:
                cols = [c['name'] for c in inspector.get_columns('donor_profiles')]
                for col_name in ['country', 'postal_code']:
                    if col_name not in cols:
                        db.session.execute(text(f"ALTER TABLE donor_profiles ADD COLUMN {col_name} VARCHAR(64)"))
                if 'verification_status' not in cols:
                    db.session.execute(text("ALTER TABLE donor_profiles ADD COLUMN verification_status VARCHAR(35) DEFAULT 'APPROVED'"))
                db.session.commit()
            if 'organizations' in tables:
                cols = [c['name'] for c in inspector.get_columns('organizations')]
                for col_name in ['country', 'postal_code']:
                    if col_name not in cols:
                        db.session.execute(text(f"ALTER TABLE organizations ADD COLUMN {col_name} VARCHAR(64)"))
            if 'users' in tables:
                cols = [c['name'] for c in inspector.get_columns('users')]
                for col_name, col_type in [
                    ('failed_login_attempts', 'INTEGER DEFAULT 0'),
                    ('last_failed_login_at', 'DATETIME'),
                    ('locked_until', 'DATETIME'),
                    ('mfa_secret', 'VARCHAR(64)'),
                    ('mfa_enabled', 'BOOLEAN DEFAULT 0')
                ]:
                    if col_name not in cols:
                        db.session.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
            if 'password_reset_tokens' not in tables:
                from app.models.user import PasswordResetToken
                PasswordResetToken.__table__.create(db.engine, checkfirst=True)
            from app.models.communication import DonorRequestResponse, DonorInvitation, Conversation, Message
            from app.models.verification import VerificationApplication, VerificationDocument
            for model_cls in [DonorRequestResponse, DonorInvitation, Conversation, Message, VerificationApplication, VerificationDocument]:
                model_cls.__table__.create(db.engine, checkfirst=True)
            if 'donor_invitations' in tables:
                inv_cols = [c['name'] for c in inspector.get_columns('donor_invitations')]
                for col_name, col_type in [
                    ('invitation_status', 'VARCHAR(30) DEFAULT "SENT"'),
                    ('message', 'TEXT'),
                    ('responded_at', 'DATETIME'),
                    ('expires_at', 'DATETIME')
                ]:
                    if col_name not in inv_cols:
                        db.session.execute(text(f"ALTER TABLE donor_invitations ADD COLUMN {col_name} {col_type}"))
            for tbl in ['users', 'organizations', 'donor_profiles', 'blood_requests', 'blood_inventories', 'donations', 'coupons']:
                if tbl in tables:
                    cols = [c['name'] for c in inspector.get_columns(tbl)]
                    if 'is_demo' not in cols:
                        db.session.execute(text(f"ALTER TABLE {tbl} ADD COLUMN is_demo BOOLEAN DEFAULT 0"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # HTTP Production Security Headers
    @app.after_request
    def apply_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(self), microphone=(), camera=()'

        # Content-Security-Policy accommodating Bootstrap, Leaflet, OpenStreetMap, Chart.js, Google Fonts
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://*.tile.openstreetmap.org https://unpkg.com; "
            "connect-src 'self' https://*.tile.openstreetmap.org https://nominatim.openstreetmap.org; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        response.headers['Content-Security-Policy'] = csp

        if app.config.get('SESSION_COOKIE_SECURE'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        return response

    # Error Handlers
    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(429)
    def ratelimit_error(error):
        return render_template('errors/429.html', error=error), 429

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500

    return app
