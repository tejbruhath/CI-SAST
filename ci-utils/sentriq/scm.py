"""
SCM provider abstraction — opens pull requests for AI-generated fixes.

GitHub is implemented first (Task B8, PR automation). The pipeline logic calls
`open_pr()` with SCM-agnostic args; the provider is chosen from the repo URL, so
adding GitLab/Bitbucket later is a new class, not a change to the callers.

All calls use a plain httpx client with the SENTRIQ_GIT_TOKEN (repo scope) and
are defensive: failures raise ScmError with a readable message rather than
leaking a raw HTTP error, so the caller can record pr_status=failed cleanly.
"""
from __future__ import annotations  # postpone evaluation of type annotations

import re  # parse owner/name from https and ssh git URLs
from dataclasses import dataclass  # simple value object for repo coordinates
from typing import Optional  # Optional token overrides

import httpx  # REST calls to GitHub API for PRs

from . import config  # GIT_TOKEN and related settings


class ScmError(Exception):
    pass  # domain error so callers avoid catching bare Exception


@dataclass
class RepoCoords:
    provider: str   # "github"  # which SCM backend to use
    owner: str  # org or user that owns the repo
    name: str       # repo name without .git

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"  # GitHub API path segment


def parse_repo(url: str) -> Optional[RepoCoords]:
    """Extract owner/name from a git remote URL. Returns None if unsupported."""
    u = url.strip()  # tolerate whitespace from form input
    u = re.sub(r"^https?://[^/@]*@", "https://", u)   # strip embedded creds
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", u)  # https form
    if m:
        return RepoCoords("github", m.group(1), m.group(2))  # owner, name groups
    # git@github.com:owner/repo.git
    m = re.match(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", u)  # ssh form
    if m:
        return RepoCoords("github", m.group(1), m.group(2))
    return None  # gitlab/bitbucket not implemented yet


# ---- GitHub ------------------------------------------------------------------
_GH_API = "https://api.github.com"  # REST API base (not github.com)


def _gh_headers(token: Optional[str] = None) -> dict:
    effective = token or config.GIT_TOKEN  # prefer acting user token
    if not effective:  # cannot authenticate the API call
        raise ScmError("SENTRIQ_GIT_TOKEN is not set — cannot open a PR")
    return {"Authorization": f"Bearer {effective}",  # OAuth/PAT bearer
            "Accept": "application/vnd.github+json",  # recommended media type
            "X-GitHub-Api-Version": "2022-11-28"}  # pin API version


def default_branch(repo: RepoCoords, token: Optional[str] = None) -> str:
    try:
        r = httpx.get(f"{_GH_API}/repos/{repo.slug}",  # repo metadata endpoint
                      headers=_gh_headers(token), timeout=30)
        r.raise_for_status()  # 404/403 become HTTPStatusError
        return r.json().get("default_branch", "main")  # fall back to main
    except httpx.HTTPStatusError as e:  # HTTP error with response body
        raise ScmError(f"GitHub repo lookup failed: {e.response.status_code} "
                       f"{e.response.text[:200]}")  # truncate noisy HTML/JSON
    except Exception as e:  # network/DNS/timeouts
        raise ScmError(f"GitHub repo lookup error: {e}")


def open_pr(repo: RepoCoords, head_branch: str, base_branch: str,
            title: str, body: str, token: Optional[str] = None) -> str:
    """Open a PR head->base; return its html_url. Raises ScmError on failure."""
    if repo.provider != "github":  # guard until other providers land
        raise ScmError(f"unsupported SCM provider: {repo.provider}")
    payload = {"title": title[:250], "head": head_branch, "base": base_branch,  # API limits
               "body": body[:60000]}  # keep body under GitHub size limits
    try:
        r = httpx.post(f"{_GH_API}/repos/{repo.slug}/pulls", json=payload,  # create PR
                       headers=_gh_headers(token), timeout=45)
        if r.status_code == 422:  # validation error — often "PR already exists"
            # Most common: a PR for this head already exists — surface its URL.
            existing = _find_existing_pr(repo, head_branch, token=token)
            if existing:
                return existing  # idempotent: reuse open PR URL
            raise ScmError(f"GitHub rejected PR (422): {r.text[:300]}")
        r.raise_for_status()  # other non-2xx become exceptions
        return r.json()["html_url"]  # browser-friendly PR link
    except httpx.HTTPStatusError as e:
        raise ScmError(f"GitHub PR create failed: {e.response.status_code} "
                       f"{e.response.text[:300]}")
    except ScmError:  # re-raise our own without wrapping
        raise
    except Exception as e:  # anything else becomes a clean ScmError
        raise ScmError(f"GitHub PR create error: {e}")


def _find_existing_pr(repo: RepoCoords, head_branch: str,
                      token: Optional[str] = None) -> Optional[str]:
    try:
        r = httpx.get(f"{_GH_API}/repos/{repo.slug}/pulls",  # list PRs
                      params={"head": f"{repo.owner}:{head_branch}", "state": "open"},  # exact head
                      headers=_gh_headers(token), timeout=30)
        r.raise_for_status()
        items = r.json()  # list of open PRs for that head
        return items[0]["html_url"] if items else None  # first match or none
    except Exception:  # soft-fail: open_pr will raise its own error
        return None


if __name__ == "__main__":  # offline unit-style checks without network
    # Offline self-check: URL parsing (no network).
    assert parse_repo("https://github.com/tejbruhath/VaulS.ai").slug == "tejbruhath/VaulS.ai"
    assert parse_repo("https://github.com/o/r.git").slug == "o/r"  # strip .git
    assert parse_repo("git@github.com:o/r.git").slug == "o/r"  # ssh form
    assert parse_repo("https://x:tok@github.com/o/r.git").slug == "o/r"  # strip creds
    assert parse_repo("https://gitlab.com/o/r.git") is None  # unsupported host
    print("scm self-check passed (github URL parsing)")
