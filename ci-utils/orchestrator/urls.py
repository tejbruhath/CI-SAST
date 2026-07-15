from django.urls import path, re_path  # path for fixed routes; re_path for optional slash.

from . import views  # View callables wired to each HTTP endpoint below.

urlpatterns = [  # Orchestrator HTTP routes under whatever prefix includes this module.
    path("health", views.health),  # Liveness/readiness: Redis ping + service name.
    path("job", views.create_job),  # POST: enqueue a new scan job.
    path("results/<str:job_id>/<str:tool>", views.save_results),  # Scanner posts tool JSON here.
    path("job/<str:job_id>/status", views.job_status),  # Poll tool sets and overall status.
    path("job/<str:job_id>/artifacts", views.get_artifacts),  # Fetch artifact then request cleanup.
    # Frontend read API (autoindex-shaped listing + raw artifact)
    re_path(r"^artifacts/?$", views.list_artifacts),  # List job folders that have artifacts.
    path("artifacts/<str:job_id>/mega-artifact.json", views.raw_artifact),  # Read-only artifact for SPA.
]
