from django.urls import path  # map URL patterns to view callables

from . import auth_views, repos_views, views  # API view modules for this app

urlpatterns = [  # routes mounted under the project URL include for sentriq
    path("health", views.health),  # liveness/readiness ping for load balancers
    path("auth/github", auth_views.github_auth),  # start GitHub OAuth login
    path("auth/github/callback", auth_views.github_callback),  # OAuth redirect landing
    path("auth/me", auth_views.me),  # current logged-in user profile JSON
    path("auth/logout", auth_views.logout_view),  # clear session / log out
    path("csrf", auth_views.csrf_token),  # give frontend a CSRF cookie/token
    path("repos", repos_views.repos),  # list GitHub repos the user can scan
    path("queue", views.queue_status),  # Celery/scan queue depth snapshot
    path("scans", views.scans),  # list or create scan runs
    path("scans/<uuid:scan_id>", views.scan_detail),  # one scan by UUID
    path("findings", views.findings),  # list findings (filters via query params)
    path("findings/<uuid:finding_id>", views.finding_detail),  # one finding detail
    path("findings/<uuid:finding_id>/fix", views.finding_fix),  # AI fix suggestion for finding
    path("findings/<uuid:finding_id>/hitl", views.finding_hitl),  # human approve/deny/edit gate
    path("findings/<uuid:finding_id>/pr", views.finding_pr),  # open PR for one fix
    path("pr", views.batch_pr),  # batch open PRs for multiple findings
    path("provenance", views.provenance),  # audit trail events for scans/findings
    path("metrics", views.metrics),  # aggregate dashboard counters
]
