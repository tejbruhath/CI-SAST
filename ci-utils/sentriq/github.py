"""GitHub OAuth and API helpers for Sentriq."""
import logging
import os
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("sentriq.github")

GITHUB_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID", "").strip()
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv(
    "GITHUB_OAUTH_REDIRECT_URI",
    "http://localhost:8000/api/v1/auth/github/callback",
)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_USER_URL = "https://api.github.com/user"
GITHUB_API_REPOS_URL = "https://api.github.com/user/repos"

MAX_REPO_PAGES = 5


def _require_credentials():
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise RuntimeError("GitHub OAuth credentials are not configured")


def github_oauth_url(state: str) -> str:
    """Build the GitHub OAuth authorize URL."""
    _require_credentials()
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "scope": "repo read:user",
        "state": state,
        "redirect_uri": REDIRECT_URI,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange a GitHub OAuth code for an access token."""
    _require_credentials()
    response = httpx.post(
        GITHUB_ACCESS_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(payload.get("error_description", payload["error"]))
    return payload


def github_user_info(access_token: str) -> dict:
    """Fetch the authenticated GitHub user's profile."""
    response = httpx.get(
        GITHUB_API_USER_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _parse_link_header(link_header: str) -> dict:
    """Parse a GitHub Link header into a rel -> url mapping."""
    links = {}
    if not link_header:
        return links
    for part in link_header.split(","):
        try:
            url, rel = part.strip().split(";")
            url = url.strip().lstrip("<").rstrip(">")
            rel = rel.strip().split("=")[1].strip('"')
            links[rel] = url
        except (ValueError, IndexError):
            continue
    return links


def list_repos(access_token: str) -> list:
    """List repositories accessible to the authenticated GitHub user.

    Follows GitHub pagination up to MAX_REPO_PAGES.
    """
    repos = []
    url = (
        f"{GITHUB_API_REPOS_URL}?"
        + urlencode({
            "per_page": "100",
            "sort": "pushed",
            "affiliation": "owner,collaborator,organization_member",
        })
    )
    pages = 0

    while url and pages < MAX_REPO_PAGES:
        response = httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        )
        response.raise_for_status()
        page_repos = response.json()
        if not isinstance(page_repos, list):
            logger.warning("Unexpected GitHub repos response: %r", page_repos)
            break
        repos.extend(page_repos)
        pages += 1
        links = _parse_link_header(response.headers.get("link", ""))
        url = links.get("next")

    return repos
