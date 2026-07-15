"""Authentication API views for GitHub OAuth and session management."""
import logging  # log create/update and exchange failures
import secrets  # cryptographically strong OAuth state nonce
from urllib.parse import urlencode  # encode error messages into redirect URLs

from django.contrib.auth import get_user_model, login, logout  # session auth helpers
from django.http import HttpResponseRedirect  # browser redirects after OAuth
from django.middleware.csrf import get_token  # issue CSRF cookie/token for SPA
from django.utils.crypto import get_random_string  # unique username suffix
from rest_framework import status  # HTTP status constants
from rest_framework.decorators import api_view, permission_classes  # DRF view helpers
from rest_framework.exceptions import NotAuthenticated  # 401 exception type
from rest_framework.permissions import AllowAny, IsAuthenticated  # access control
from rest_framework.response import Response  # JSON responses
from rest_framework.views import exception_handler as drf_exception_handler  # default handler

from django.conf import settings  # FRONTEND_URL and other Django settings

from .github import (  # GitHub OAuth/API helpers used by these views
    exchange_code,
    github_oauth_url,
    github_user_info,
    revoke_token,
)
from .models import UserProfile  # stores github_id, token, avatar per user
from .crypto import decrypt_token, encrypt_token  # protect token at rest

logger = logging.getLogger("sentriq.auth")  # auth subsystem logger

User = get_user_model()  # project user model (custom or default)

FRONTEND_URL = settings.FRONTEND_URL  # SPA origin for post-login redirects


def _error_redirect(message: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(  # send browser back to SPA with error query
        f"{FRONTEND_URL}/?{urlencode({'login': 'error', 'message': message})}"
    )


@api_view(["GET"])  # SPA fetches authorize URL via GET
@permission_classes([AllowAny])  # login start is public
def github_auth(request):
    """Return the GitHub OAuth URL with a random state stored in session."""
    state = secrets.token_urlsafe(32)  # unpredictable CSRF state
    request.session["github_oauth_state"] = state  # store for callback check
    request.session.modified = True  # force session save
    return Response({"url": github_oauth_url(state)})  # SPA redirects the browser


@api_view(["GET"])  # GitHub redirects the browser here
@permission_classes([AllowAny])  # callback is public but state-protected
def github_callback(request):
    """Handle the GitHub OAuth callback, create/update the user, and redirect."""
    code = request.query_params.get("code")  # one-time authorization code
    state = request.query_params.get("state")  # must match session value
    expected_state = request.session.get("github_oauth_state")  # previously stored

    if not code or not state:  # incomplete callback from GitHub
        return _error_redirect("missing OAuth code or state")

    if not expected_state or state != expected_state:  # CSRF / replay attempt
        return _error_redirect("invalid OAuth state")

    # State is single-use.
    request.session.pop("github_oauth_state", None)  # prevent reuse of state
    request.session.modified = True

    try:
        token_payload = exchange_code(code)  # trade code for access_token
    except Exception as exc:  # noqa: BLE001
        logger.exception("GitHub token exchange failed")
        return _error_redirect(f"GitHub token exchange failed: {exc}")

    access_token = token_payload.get("access_token")  # required for API calls
    if not access_token:  # GitHub returned success-shaped body without token
        return _error_redirect("GitHub did not return an access token")

    try:
        gh_user = github_user_info(access_token)  # fetch profile fields
    except Exception as exc:  # noqa: BLE001
        logger.exception("GitHub user info fetch failed")
        return _error_redirect(f"GitHub user info fetch failed: {exc}")

    github_id = str(gh_user.get("id", ""))  # stable unique id (stringified)
    github_login = gh_user.get("login", "")  # @username handle
    name = gh_user.get("name", "") or ""  # display name may be null
    avatar_url = gh_user.get("avatar_url", "") or ""  # profile picture URL

    if not github_id or not github_login:  # incomplete profile is unusable
        return _error_redirect("GitHub user info incomplete")

    try:
        profile = UserProfile.objects.select_related("user").get(github_id=github_id)  # returning user
        user = profile.user  # Django auth user linked to profile
        created = False  # existing account path
    except UserProfile.DoesNotExist:  # first login for this GitHub id
        # Ensure a unique local username in case of collisions.
        username = github_login  # prefer exact GitHub login
        if User.objects.filter(username=username).exists():  # collision with someone else
            username = f"{github_login}_{get_random_string(8)}"  # uniquify
        user = User.objects.create_user(  # create Django user without password
            username=username,
            first_name=name,
        )
        profile = UserProfile(user=user, github_id=github_id)  # link profile
        created = True  # need full save below

    # Keep Django username and display name in sync with GitHub, but never
    # overwrite a username already claimed by another account.
    if not User.objects.exclude(pk=user.pk).filter(username=github_login).exists():
        user.username = github_login  # reclaim preferred login when free
    user.first_name = name  # refresh display name from GitHub
    user.save(update_fields=["username", "first_name"])  # persist user fields only

    profile.github_login = github_login  # keep handle current
    profile.github_access_token = encrypt_token(access_token)  # store encrypted
    profile.avatar_url = avatar_url  # cache avatar for UI
    profile.save(
        update_fields=None if created  # first insert: save all fields
        else ["github_login", "github_access_token", "avatar_url"]  # update subset
    )

    logger.info(
        "%s GitHub user id=%s login=%s",
        "created" if created else "updated",  # which path we took
        github_id,
        github_login,
    )

    login(request, user)  # establish Django session cookie
    return HttpResponseRedirect(f"{FRONTEND_URL}/?login=success")  # SPA success flag


@api_view(["GET"])
@permission_classes([IsAuthenticated])  # only logged-in users
def me(request):
    """Return the current authenticated user's profile."""
    user = request.user  # session user
    profile = getattr(user, "sentriq_profile", None)  # may be missing for non-GH users
    return Response({
        "id": user.id,  # local primary key
        "login": profile.github_login if profile else user.username,  # prefer GH login
        "name": user.get_full_name() or user.username,  # display name fallback
        "avatar_url": profile.avatar_url if profile else "",  # empty if no profile
    })


@api_view(["POST"])  # logout is a state-changing action
@permission_classes([IsAuthenticated])
def logout_view(request):
    """Log the current user out and revoke the stored GitHub token."""
    profile = getattr(request.user, "sentriq_profile", None)
    if profile:  # clear remote + local token when present
        access_token = decrypt_token(profile.github_access_token)  # plaintext for revoke
        if access_token:
            revoke_token(access_token)  # best-effort GitHub revoke
        profile.github_access_token = ""  # wipe local copy
        profile.save(update_fields=["github_access_token"])

    logout(request)  # clear Django session
    return Response({"status": "logged_out"})  # SPA can clear client state


@api_view(["GET"])
@permission_classes([AllowAny])  # SPA needs CSRF before login POST flows
def csrf_token(request):
    """Ensure the CSRF cookie is set for the SPA."""
    token = get_token(request)  # sets cookie and returns token value
    return Response({"detail": "ok", "csrftoken": token})  # also return in body


def auth_exception_handler(exc, context):
    """Return HTTP 401 for unauthenticated requests so the SPA can detect logout."""
    if isinstance(exc, NotAuthenticated):  # DRF default would often be 403
        return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
    return drf_exception_handler(exc, context)  # fall back to DRF defaults
