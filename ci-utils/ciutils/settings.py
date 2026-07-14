"""
Django settings for the Sentriq backend (evolved from ci-utils).

Change from the original ci-utils: this service now has a relational system of
record (Postgres) for scans, findings, triage, fixes, HITL actions and the
provenance/audit trail. Redis is retained purely as the Celery broker/result
backend. Scanners run locally (docker/subprocess via Celery), not as k8s Jobs.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load local .env for terminal-based dev (backend/worker run outside Docker).
# .env lives at the project root, one directory above ci-utils/.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "sentriq-dev-not-secret")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "rest_framework",
    "corsheaders",
    "sentriq",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "ciutils.urls"
WSGI_APPLICATION = "ciutils.wsgi.application"
TEMPLATES = []

if os.getenv("USE_SQLITE") == "1":
    # Local-only escape hatch (e.g. running checks/migrations without Postgres).
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                             "NAME": os.path.join(BASE_DIR, "local.sqlite3")}}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "sentriq"),
            "USER": os.getenv("POSTGRES_USER", "sentriq"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "sentriq"),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 100,
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "sentriq.auth_views.auth_exception_handler",
}

# CORS: allow the React dev frontend to send cookies.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost(:\d+)?$",
    r"^http://127\.0\.0\.1(:\d+)?$",
]
CSRF_TRUSTED_ORIGINS = [
    FRONTEND_URL,
]

# Sessions / CSRF cookies for SPA auth.
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
SESSION_COOKIE_NAME = "sentriq_sessionid"
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", "28800"))
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # JS needs to read the token for API calls.
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_NAME = "sentriq_csrftoken"
CSRF_USE_SESSIONS = False

# ---- Celery ------------------------------------------------------------------
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "3600"))

USE_TZ = True
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "ci": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "ci"},
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    "loggers": {
        "sentriq": {
            "handlers": ["console"],
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
