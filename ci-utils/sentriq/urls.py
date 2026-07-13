from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    path("scans", views.scans),
    path("scans/<uuid:scan_id>", views.scan_detail),
    path("findings", views.findings),
    path("findings/<uuid:finding_id>", views.finding_detail),
    path("findings/<uuid:finding_id>/hitl", views.finding_hitl),
    path("findings/<uuid:finding_id>/pr", views.finding_pr),
    path("provenance", views.provenance),
    path("metrics", views.metrics),
]
