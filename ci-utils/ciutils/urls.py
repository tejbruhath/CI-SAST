from django.urls import include, path  # path builds routes; include nests app URLconfs.

urlpatterns = [  # Root URL table Django matches against incoming paths.
    path("api/v1/", include("sentriq.urls")),  # Mount the product API under /api/v1/.
]
