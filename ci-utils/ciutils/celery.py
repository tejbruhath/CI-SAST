"""Celery application for Sentriq background scan orchestration."""
import os  # Read process env so Django settings path can be set.

from celery import Celery  # Celery app factory for async task workers.
from celery.schedules import crontab  # Cron-like schedules for periodic Beat tasks.

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ciutils.settings")  # Default Django settings if unset.

app = Celery("sentriq")  # Create named Celery app used by workers and Beat.
app.config_from_object("django.conf:settings", namespace="CELERY")  # Load CELERY_* keys from Django settings.
app.autodiscover_tasks()  # Find @shared_task modules in installed Django apps.

app.conf.beat_schedule = {  # Periodic tasks Celery Beat will fire on a timer.
    "reap-orphaned-scans": {  # Human-readable schedule entry name for ops/logs.
        "task": "sentriq.reap_orphaned_scans",  # Fully-qualified task path to invoke.
        "schedule": crontab(minute="*/10"),  # Run every ten minutes on the clock.
    },
}
