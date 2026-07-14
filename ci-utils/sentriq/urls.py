from django.urls import path

from . import auth_views, repos_views, views

urlpatterns = [
    path("health", views.health),
    path("auth/github", auth_views.github_auth),
    path("auth/github/callback", auth_views.github_callback),
    path("auth/me", auth_views.me),
    path("auth/logout", auth_views.logout_view),
    path("csrf", auth_views.csrf_token),
    path("repos", repos_views.repos),
    path("queue", views.queue_status),
    path("scans", views.scans),
    path("scans/<uuid:scan_id>", views.scan_detail),
    path("findings", views.findings),
    path("findings/<uuid:finding_id>", views.finding_detail),
    path("findings/<uuid:finding_id>/hitl", views.finding_hitl),
    path("findings/<uuid:finding_id>/pr", views.finding_pr),
    path("provenance", views.provenance),
    path("metrics", views.metrics),
]
