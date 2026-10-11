from flask import request, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


def get_client_ip():
    """Extract real client IP safely, respecting trusted proxy configuration."""
    try:
        if current_app and current_app.config.get('BEHIND_TRUSTED_PROXY'):
            return request.access_route[0] if request.access_route else request.remote_addr
        return request.remote_addr or '127.0.0.1'
    except Exception:
        return '127.0.0.1'


limiter = Limiter(
    key_func=get_client_ip,
    default_limits=[]
)

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

