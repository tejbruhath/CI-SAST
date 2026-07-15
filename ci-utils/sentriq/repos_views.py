"""Repository API views for Sentriq."""
import logging  # log GitHub API failures with stack traces

from rest_framework import status  # HTTP status codes for Response
from rest_framework.decorators import api_view, permission_classes  # view wiring
from rest_framework.permissions import IsAuthenticated  # require logged-in user
from rest_framework.response import Response  # JSON API responses

from .crypto import decrypt_token  # decrypt stored OAuth token at rest
from .github import list_repos  # paginated GitHub user repos fetch

logger = logging.getLogger("sentriq.repos")  # module logger

_REPO_FIELDS = ("id", "full_name", "clone_url", "default_branch", "private", "html_url", "description")  # whitelist


@api_view(["GET"])  # only GET is allowed for this endpoint
@permission_classes([IsAuthenticated])  # reject anonymous callers
def repos(request):
    """List repositories accessible to the authenticated GitHub user."""
    user = request.user  # Django user from session auth
    profile = getattr(user, "sentriq_profile", None)  # OneToOne profile if present
    if not profile or not profile.github_access_token:  # never linked GitHub
        return Response(
            {"detail": "GitHub account not connected"},
            status=status.HTTP_401_UNAUTHORIZED,  # client should re-auth
        )

    access_token = decrypt_token(profile.github_access_token)  # plaintext token
    if not access_token:  # decrypt failed or empty ciphertext
        return Response(
            {"detail": "Stored GitHub token is invalid or missing"},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        raw_repos = list_repos(access_token)  # call GitHub with user token
    except Exception as exc:  # noqa: BLE001  # surface as 502, not 500 crash
        logger.exception("Failed to list GitHub repos for user %s", user.id)
        return Response(
            {"detail": f"GitHub API error: {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,  # upstream dependency failed
        )

    result = []  # filtered list for the SPA
    for repo in raw_repos:
        if not isinstance(repo, dict):  # skip unexpected payload shapes
            continue
        filtered = {key: repo.get(key) for key in _REPO_FIELDS}  # drop extra fields
        # Ensure boolean serialization for private flag.
        filtered["private"] = bool(filtered.get("private"))  # normalize null/0
        result.append(filtered)

    return Response(result)  # 200 JSON array of slim repo objects
