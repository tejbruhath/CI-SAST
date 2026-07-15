"""GitHub OAuth and API helpers for Sentriq."""
import logging  # warnings when revoke or list_repos misbehaves
import os  # read OAuth client id/secret and redirect URI
from urllib.parse import urlencode  # build safe query strings for OAuth URLs

import httpx  # sync HTTP client for GitHub OAuth + REST

logger = logging.getLogger("sentriq.github")  # module-level logger name

GITHUB_CLIENT_ID = os.getenv("GITHUB_OAUTH_CLIENT_ID", "").strip()  # OAuth app client id
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "").strip()  # never expose to browser
REDIRECT_URI = os.getenv(  # must match GitHub OAuth app callback setting
    "GITHUB_OAUTH_REDIRECT_URI",
    "http://localhost:8000/api/v1/auth/github/callback",  # local dev default
)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"  # browser redirect start
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"  # code → token
GITHUB_API_USER_URL = "https://api.github.com/user"  # authenticated profile
GITHUB_API_REPOS_URL = "https://api.github.com/user/repos"  # repos the user can access
# Revokes just this access token, not the whole authorization grant. The grant
# endpoint (.../grant) would also work but forces the user through GitHub's
# consent screen on every subsequent login for no extra security.
GITHUB_REVOKE_TOKEN_URL = "https://api.github.com/applications/{client_id}/token"  # DELETE token

MAX_REPO_PAGES = 5  # cap pagination so listing cannot run forever


def _require_credentials():
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:  # misconfigured deploy
        raise RuntimeError("GitHub OAuth credentials are not configured")


def github_oauth_url(state: str) -> str:
    """Build the GitHub OAuth authorize URL."""
    _require_credentials()  # fail early before sending user to GitHub
    params = {
        "client_id": GITHUB_CLIENT_ID,  # identifies our OAuth app
        "scope": "repo read:user",  # private repos + basic profile
        "state": state,  # CSRF nonce checked on callback
        "redirect_uri": REDIRECT_URI,  # where GitHub sends the user back
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"  # full authorize URL


def exchange_code(code: str) -> dict:
    """Exchange a GitHub OAuth code for an access token."""
    _require_credentials()  # need secret for token exchange
    response = httpx.post(  # server-side POST; never put secret in browser
        GITHUB_ACCESS_TOKEN_URL,
        headers={"Accept": "application/json"},  # ask for JSON, not form body
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,  # proves we own the app
            "code": code,  # one-time code from the callback
            "redirect_uri": REDIRECT_URI,  # must match authorize step
        },
        timeout=30,  # avoid hanging the login request forever
    )
    response.raise_for_status()  # HTTP errors become exceptions
    payload = response.json()  # token payload or error object
    if "error" in payload:  # GitHub returns 200 with error field sometimes
        raise RuntimeError(payload.get("error_description", payload["error"]))
    return payload  # includes access_token and scopes


def github_user_info(access_token: str) -> dict:
    """Fetch the authenticated GitHub user's profile."""
    response = httpx.get(  # who owns this token?
        GITHUB_API_USER_URL,
        headers={
            "Authorization": f"Bearer {access_token}",  # OAuth bearer token
            "Accept": "application/vnd.github+json",  # GitHub JSON media type
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()  # id, login, name, avatar_url, etc.


def revoke_token(access_token: str) -> None:
    """Revoke a GitHub OAuth access token.

    Uses HTTP Basic authentication (client_id:client_secret). Any non-2xx
    response (except 404, which means the token is already gone) is logged as
    a warning and never raised — failing to revoke must never block logout.
    """
    if not access_token or not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:  # nothing to do
        return

    url = GITHUB_REVOKE_TOKEN_URL.format(client_id=GITHUB_CLIENT_ID)  # fill path param
    try:
        response = httpx.request(  # DELETE with body needs request(), not delete()
            "DELETE",
            url,
            auth=(GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET),  # HTTP Basic for app auth
            json={"access_token": access_token},  # which user token to revoke
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001  # network blip must not break logout
        logger.warning("Failed to revoke GitHub token: %s", exc)
        return

    if response.status_code in (200, 204):  # successfully revoked
        logger.info("Revoked GitHub token for client %s", GITHUB_CLIENT_ID)
        return

    if response.status_code == 404:  # already gone — fine for logout
        logger.info("GitHub token already revoked (404)")
        return

    logger.warning(  # unexpected status still non-fatal
        "GitHub token revoke returned unexpected status %s: %s",
        response.status_code,
        response.text,
    )


def _parse_link_header(link_header: str) -> dict:
    """Parse a GitHub Link header into a rel -> url mapping."""
    links = {}  # e.g. {"next": "https://...", "last": "..."}
    if not link_header:  # no pagination header
        return links
    for part in link_header.split(","):  # multiple links separated by commas
        try:
            url, rel = part.strip().split(";")  # "<url>; rel=\"next\""
            url = url.strip().lstrip("<").rstrip(">")  # strip angle brackets
            rel = rel.strip().split("=")[1].strip('"')  # extract rel value
            links[rel] = url  # map relation name to URL
        except (ValueError, IndexError):  # skip malformed segments
            continue
    return links


def list_repos(access_token: str) -> list:
    """List repositories accessible to the authenticated GitHub user.

    Follows GitHub pagination up to MAX_REPO_PAGES.
    """
    repos = []  # accumulate all pages
    url = (  # first page with sensible defaults
        f"{GITHUB_API_REPOS_URL}?"
        + urlencode({
            "per_page": "100",  # max page size GitHub allows
            "sort": "pushed",  # recently active repos first
            "affiliation": "owner,collaborator,organization_member",  # all roles
        })
    )
    pages = 0  # how many pages we have fetched

    while url and pages < MAX_REPO_PAGES:  # stop at next=None or page cap
        response = httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        )
        response.raise_for_status()
        page_repos = response.json()  # expect a JSON array
        if not isinstance(page_repos, list):  # defensive against API changes
            logger.warning("Unexpected GitHub repos response: %r", page_repos)
            break
        repos.extend(page_repos)  # append this page of repos
        pages += 1
        links = _parse_link_header(response.headers.get("link", ""))  # pagination
        url = links.get("next")  # None ends the loop

    return repos  # flat list of raw GitHub repo dicts
