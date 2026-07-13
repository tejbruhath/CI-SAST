"""Celery application for Sentriq background scan orchestration."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ciutils.settings")

app = Celery("sentriq")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
