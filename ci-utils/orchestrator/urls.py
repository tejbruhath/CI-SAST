from django.urls import path, re_path

from . import views

urlpatterns = [
    path("health", views.health),
    path("job", views.create_job),
    path("results/<str:job_id>/<str:tool>", views.save_results),
    path("job/<str:job_id>/status", views.job_status),
    path("job/<str:job_id>/artifacts", views.get_artifacts),
    # Frontend read API (autoindex-shaped listing + raw artifact)
    re_path(r"^artifacts/?$", views.list_artifacts),
    path("artifacts/<str:job_id>/mega-artifact.json", views.raw_artifact),
]
