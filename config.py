import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = (BASE_DIR / 'instance').resolve()
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DB_FILE = (INSTANCE_DIR / 'bloodlink.db').resolve()


def get_database_url():
    url = os.environ.get('DATABASE_URL')
    if url:
        # Render / Heroku compatibility for SQLAlchemy 2.0
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        # Normalize SQLite paths to prevent split/duplicate databases
        if url.startswith("sqlite:///"):
            path_part = url[len("sqlite:///"):].strip()
            if path_part == ":memory:":
                return "sqlite:///:memory:"
            # If path is relative, always resolve it inside the canonical instance directory
            if not os.path.isabs(path_part):
                db_filename = os.path.basename(path_part) or 'bloodlink.db'
                resolved_path = (INSTANCE_DIR / db_filename).resolve().as_posix()
                return f"sqlite:///{resolved_path}"
            else:
                posix_path = Path(path_part).resolve().as_posix()
                return f"sqlite:///{posix_path}"
        return url
    return f"sqlite:///{DEFAULT_DB_FILE.as_posix()}"


class Config:
    """Base application configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'bloodlink-ai-dev-secret-key-2026-hackathon')
    SQLALCHEMY_DATABASE_URI = get_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Engine connection options (30-second timeout to handle concurrent DB Browser inspection gracefully)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'timeout': 30}
    }
    
    # Security & Session Settings
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = True
    
    # Rate Limiting & Brute-Force Defenses (Flask-Limiter)
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_STRATEGY = 'fixed-window'
    RATELIMIT_DEFAULT = os.environ.get('RATELIMIT_DEFAULT', '300 per minute')
    LOGIN_RATE_LIMIT = os.environ.get('LOGIN_RATE_LIMIT', '10 per minute; 50 per hour')
    REGISTER_RATE_LIMIT = os.environ.get('REGISTER_RATE_LIMIT', '20 per minute; 100 per hour')
    PASSWORD_RESET_RATE_LIMIT = os.environ.get('PASSWORD_RESET_RATE_LIMIT', '3 per minute; 10 per hour')
    
    # Account Lockout & Throttling Defaults
    MAX_FAILED_LOGIN_ATTEMPTS = int(os.environ.get('MAX_FAILED_LOGIN_ATTEMPTS', '5'))
    LOGIN_LOCKOUT_MINUTES = int(os.environ.get('LOGIN_LOCKOUT_MINUTES', '15'))
    PASSWORD_RESET_TOKEN_MINUTES = int(os.environ.get('PASSWORD_RESET_TOKEN_MINUTES', '15'))
    
    # Administrator MFA Enforcement
    REQUIRE_ADMIN_MFA = os.environ.get('REQUIRE_ADMIN_MFA', 'false').lower() == 'true'
    
    # BloodLink AI Domain Rules
    DONATION_COOLDOWN_DAYS = 56  # Standard WHO cooldown interval
    MAX_MATCH_DISTANCE_KM = 75.0
    
    # Configurable Prioritization Weights (Demonstration values)
    PRIORITY_WEIGHTS = {
        'urgency': 40.0,
        'time_sensitivity': 30.0,
        'inventory_shortage': 20.0,
        'waiting_time': 10.0
    }
    
    # Configurable Donor Matching Weights
    MATCH_WEIGHTS = {
        'proximity': 0.35,
        'availability': 0.30,
        'recency': 0.20,
        'suitability': 0.15
    }


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False  # Dedicated tests selectively enable limiter


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    REQUIRE_ADMIN_MFA = True
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }


config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
