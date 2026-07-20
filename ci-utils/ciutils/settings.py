"""
Django settings for the Sentriq backend (evolved from ci-utils).

Change from the original ci-utils: this service now has a relational system of
record (Postgres) for scans, findings, triage, fixes, HITL actions and the
provenance/audit trail. Redis is retained purely as the Celery broker/result
backend. Scanners run locally (docker/subprocess via Celery), not as k8s Jobs.
"""
import os  # Read environment variables for secrets and deployment config.
from pathlib import Path  # Path helpers to locate the project-root .env file.

from dotenv import load_dotenv  # Load KEY=value pairs from a local .env file.

# Load local .env for terminal-based dev (backend/worker run outside Docker).
# .env lives at the project root, one directory above ci-utils/.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")  # Inject .env into os.environ early.

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Project root (parent of ciutils/).

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "sentriq-dev-not-secret")  # Signing key; override in production.
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"  # Verbose errors only when explicitly enabled.
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")  # Hostnames Django accepts in the Host header.

INSTALLED_APPS = [  # Django/DRF apps loaded at startup for models and APIs.
    "django.contrib.contenttypes",  # Generic relations; needed by auth and sessions.
    "django.contrib.auth",  # User model and authentication plumbing.
    "django.contrib.sessions",  # Server-side sessions for cookie-based SPA login.
    "rest_framework",  # Django REST Framework for JSON APIs.
    "corsheaders",  # Browser CORS so the React frontend can call the API.
    "sentriq",  # Main product app: scans, findings, auth views, tasks.
]

MIDDLEWARE = [  # Request/response pipeline; order matters for CORS and CSRF.
    "corsheaders.middleware.CorsMiddleware",  # Must be early so CORS headers attach first.
    "django.middleware.security.SecurityMiddleware",  # Security headers and HTTPS redirects.
    "django.contrib.sessions.middleware.SessionMiddleware",  # Load/save session from cookies.
    "django.middleware.common.CommonMiddleware",  # URL cleanup and content-type defaults.
    "django.middleware.csrf.CsrfViewMiddleware",  # Block cross-site POST without CSRF token.
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # Attach request.user from session.
    "django.contrib.messages.middleware.MessageMiddleware",  # Flash messages (mostly unused here).
]

ROOT_URLCONF = "ciutils.urls"  # Root URL module that includes app routes.
WSGI_APPLICATION = "ciutils.wsgi.application"  # WSGI entrypoint for gunicorn/uWSGI.
TEMPLATES = []  # No Django templates; API-only backend.

if os.getenv("USE_SQLITE") == "1":  # Dev escape hatch when Postgres is unavailable.
    # Local-only escape hatch (e.g. running checks/migrations without Postgres).
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",  # Lightweight file-based DB engine.
                             "NAME": os.path.join(BASE_DIR, "local.sqlite3")}}  # SQLite file under project root.
else:
    DATABASES = {  # Production-style default: Postgres as system of record.
        "default": {
            "ENGINE": "django.db.backends.postgresql",  # Use psycopg with Postgres.
            "NAME": os.getenv("POSTGRES_DB", "sentriq"),  # Database name inside Postgres.
            "USER": os.getenv("POSTGRES_USER", "sentriq"),  # DB role for app connections.
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "sentriq"),  # DB password from env/secrets.
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),  # Hostname of Postgres service.
            "PORT": os.getenv("POSTGRES_PORT", "5432"),  # Postgres listen port (default 5432).
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"  # Default primary key type for new models.

REST_FRAMEWORK = {  # Global DRF defaults for auth, permissions, and JSON I/O.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",  # Cookie/session auth for SPA.
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],  # Require login by default.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],  # Always respond with JSON.
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],  # Accept JSON request bodies.
    "UNAUTHENTICATED_USER": None,  # Anonymous user is None instead of AnonymousUser.
    "EXCEPTION_HANDLER": "sentriq.auth_views.auth_exception_handler",  # Custom API error JSON shape.
}

# CORS: allow the React dev frontend to send cookies.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")  # SPA origin for CSRF trusted list.

CORS_ALLOW_ALL_ORIGINS = False  # Never open CORS to the entire internet.
CORS_ALLOW_CREDENTIALS = True  # Allow cookies/credentials on cross-origin requests.
CORS_ALLOWED_ORIGIN_REGEXES = [  # Localhost (any port) may call the API in dev.
    r"^http://localhost(:\d+)?$",  # Match http://localhost and optional port.
    r"^http://127\.0\.0\.1(:\d+)?$",  # Match loopback IP with optional port.
]
CSRF_TRUSTED_ORIGINS = [  # Origins allowed to send cookie-authenticated POSTs.
    FRONTEND_URL,  # Trust the configured frontend URL for CSRF checks.
]

# Sessions / CSRF cookies for SPA auth.
SESSION_COOKIE_SAMESITE = "Lax"  # Send session cookie on top-level navigations only.
SESSION_COOKIE_HTTPONLY = True  # JS cannot read session cookie (XSS mitigation).
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"  # HTTPS-only when true.
SESSION_COOKIE_NAME = "sentriq_sessionid"  # Custom name avoids clashing with other Django apps.
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", "28800"))  # Session lifetime: 8 hours default.
SESSION_SAVE_EVERY_REQUEST = True  # Refresh session expiry on each authenticated request.
CSRF_COOKIE_SAMESITE = "Lax"  # SameSite policy matching the session cookie.
CSRF_COOKIE_HTTPONLY = False  # JS needs to read the token for API calls.
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE  # CSRF cookie follows same HTTPS rule as session.
CSRF_COOKIE_NAME = "sentriq_csrftoken"  # Named CSRF cookie the SPA can locate and send.
CSRF_USE_SESSIONS = False  # Store CSRF token in a cookie, not the session store.

# ---- Celery ------------------------------------------------------------------
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # Queue broker for task messages.
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # Where task results are stored.
CELERY_TASK_TRACK_STARTED = True  # Emit STARTED state so UIs can show progress.
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "3600"))  # Hard kill long tasks after 1h.

USE_TZ = True  # Store datetimes timezone-aware in the database.
LANGUAGE_CODE = "en-us"  # Default language for Django i18n machinery.
TIME_ZONE = "UTC"  # Canonical timezone for timestamps and schedules.

LOGGING = {  # Structured console logging for the app and workers.
    "version": 1,  # DictConfig schema version required by Python logging.
    "disable_existing_loggers": False,  # Keep library loggers; do not silence them.
    "formatters": {
        "ci": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},  # Timestamped human-readable lines.
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "ci"},  # Print logs to stdout/stderr.
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},  # Default level for all loggers.
    "loggers": {
        "sentriq": {  # Dedicated logger namespace for product code.
            "handlers": ["console"],  # Emit sentriq logs to the console handler.
            "level": os.getenv("LOG_LEVEL", "INFO"),  # Same level knob as root unless overridden.
            "propagate": False,  # Avoid double-printing via the root logger.
        },
    },
}
