"""Ensure the Celery app is loaded when Django starts (so @shared_task binds)."""
from .celery import app as celery_app  # Import app so workers share one Celery instance.

__all__ = ("celery_app",)  # Public exports when someone does `from ciutils import *`.
