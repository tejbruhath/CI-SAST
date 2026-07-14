"""Authentication API views for GitHub OAuth and session management."""
import logging
import secrets
from urllib.parse import urlencode

from django.contrib.auth import get_user_model, login, logout
from django.http import HttpResponseRedirect
from django.middleware.csrf import get_token
from django.utils.crypto import get_random_string
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from django.conf import settings

from .github import (
    exchange_code,
    github_oauth_url,
    github_user_info,
)
from .models import UserProfile
from .crypto import encrypt_token

logger = logging.getLogger("sentriq.auth")

User = get_user_model()

FRONTEND_URL = settings.FRONTEND_URL


def _error_redirect(message: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(
        f"{FRONTEND_URL}/?{urlencode({'login': 'error', 'message': message})}"
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def github_auth(request):
    """Return the GitHub OAuth URL with a random state stored in session."""
    state = secrets.token_urlsafe(32)
    request.session["github_oauth_state"] = state
    request.session.modified = True
    return Response({"url": github_oauth_url(state)})


@api_view(["GET"])
@permission_classes([AllowAny])
def github_callback(request):
    """Handle the GitHub OAuth callback, create/update the user, and redirect."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    expected_state = request.session.get("github_oauth_state")

    if not code or not state:
        return _error_redirect("missing OAuth code or state")

    if not expected_state or state != expected_state:
        return _error_redirect("invalid OAuth state")

    # State is single-use.
    request.session.pop("github_oauth_state", None)
    request.session.modified = True

    try:
        token_payload = exchange_code(code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("GitHub token exchange failed")
        return _error_redirect(f"GitHub token exchange failed: {exc}")

    access_token = token_payload.get("access_token")
    if not access_token:
        return _error_redirect("GitHub did not return an access token")

    try:
        gh_user = github_user_info(access_token)
    except Exception as exc:  # noqa: BLE001
        logger.exception("GitHub user info fetch failed")
        return _error_redirect(f"GitHub user info fetch failed: {exc}")

    github_id = str(gh_user.get("id", ""))
    github_login = gh_user.get("login", "")
    name = gh_user.get("name", "") or ""
    avatar_url = gh_user.get("avatar_url", "") or ""

    if not github_id or not github_login:
        return _error_redirect("GitHub user info incomplete")

    try:
        profile = UserProfile.objects.select_related("user").get(github_id=github_id)
        user = profile.user
        created = False
    except UserProfile.DoesNotExist:
        # Ensure a unique local username in case of collisions.
        username = github_login
        if User.objects.filter(username=username).exists():
            username = f"{github_login}_{get_random_string(8)}"
        user = User.objects.create_user(
            username=username,
            first_name=name,
        )
        profile = UserProfile(user=user, github_id=github_id)
        created = True

    # Keep Django username and display name in sync with GitHub, but never
    # overwrite a username already claimed by another account.
    if not User.objects.exclude(pk=user.pk).filter(username=github_login).exists():
        user.username = github_login
    user.first_name = name
    user.save(update_fields=["username", "first_name"])

    profile.github_login = github_login
    profile.github_access_token = encrypt_token(access_token)
    profile.avatar_url = avatar_url
    profile.save(
        update_fields=None if created
        else ["github_login", "github_access_token", "avatar_url"]
    )

    logger.info(
        "%s GitHub user id=%s login=%s",
        "created" if created else "updated",
        github_id,
        github_login,
    )

    login(request, user)
    return HttpResponseRedirect(f"{FRONTEND_URL}/?login=success")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    """Return the current authenticated user's profile."""
    user = request.user
    profile = getattr(user, "sentriq_profile", None)
    return Response({
        "id": user.id,
        "login": profile.github_login if profile else user.username,
        "name": user.get_full_name() or user.username,
        "avatar_url": profile.avatar_url if profile else "",
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """Log the current user out."""
    logout(request)
    return Response({"status": "logged_out"})


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_token(request):
    """Ensure the CSRF cookie is set for the SPA."""
    token = get_token(request)
    return Response({"detail": "ok", "csrftoken": token})
