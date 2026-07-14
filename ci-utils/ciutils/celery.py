"""Celery application for Sentriq background scan orchestration."""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ciutils.settings")

app = Celery("sentriq")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "reap-orphaned-scans": {
        "task": "sentriq.reap_orphaned_scans",
        "schedule": crontab(minute="*/10"),
    },
}
