"""Repository API views for Sentriq."""
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .crypto import decrypt_token
from .github import list_repos

logger = logging.getLogger("sentriq.repos")

_REPO_FIELDS = ("id", "full_name", "clone_url", "default_branch", "private", "html_url", "description")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def repos(request):
    """List repositories accessible to the authenticated GitHub user."""
    user = request.user
    profile = getattr(user, "sentriq_profile", None)
    if not profile or not profile.github_access_token:
        return Response(
            {"detail": "GitHub account not connected"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    access_token = decrypt_token(profile.github_access_token)
    if not access_token:
        return Response(
            {"detail": "Stored GitHub token is invalid or missing"},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        raw_repos = list_repos(access_token)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to list GitHub repos for user %s", user.id)
        return Response(
            {"detail": f"GitHub API error: {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    result = []
    for repo in raw_repos:
        if not isinstance(repo, dict):
            continue
        filtered = {key: repo.get(key) for key in _REPO_FIELDS}
        # Ensure boolean serialization for private flag.
        filtered["private"] = bool(filtered.get("private"))
        result.append(filtered)

    return Response(result)
