"""
SCM provider abstraction — opens pull requests for AI-generated fixes.

GitHub is implemented first (Task B8, PR automation). The pipeline logic calls
`open_pr()` with SCM-agnostic args; the provider is chosen from the repo URL, so
adding GitLab/Bitbucket later is a new class, not a change to the callers.

All calls use a plain httpx client with the SENTRIQ_GIT_TOKEN (repo scope) and
are defensive: failures raise ScmError with a readable message rather than
leaking a raw HTTP error, so the caller can record pr_status=failed cleanly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import httpx

from . import config


class ScmError(Exception):
    pass


@dataclass
class RepoCoords:
    provider: str   # "github"
    owner: str
    name: str       # repo name without .git

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


def parse_repo(url: str) -> Optional[RepoCoords]:
    """Extract owner/name from a git remote URL. Returns None if unsupported."""
    u = url.strip()
    u = re.sub(r"^https?://[^/@]*@", "https://", u)   # strip embedded creds
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", u)
    if m:
        return RepoCoords("github", m.group(1), m.group(2))
    # git@github.com:owner/repo.git
    m = re.match(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", u)
    if m:
        return RepoCoords("github", m.group(1), m.group(2))
    return None


# ---- GitHub ------------------------------------------------------------------
_GH_API = "https://api.github.com"


def _gh_headers(token: Optional[str] = None) -> dict:
    effective = token or config.GIT_TOKEN
    if not effective:
        raise ScmError("SENTRIQ_GIT_TOKEN is not set — cannot open a PR")
    return {"Authorization": f"Bearer {effective}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def default_branch(repo: RepoCoords, token: Optional[str] = None) -> str:
    try:
        r = httpx.get(f"{_GH_API}/repos/{repo.slug}",
                      headers=_gh_headers(token), timeout=30)
        r.raise_for_status()
        return r.json().get("default_branch", "main")
    except httpx.HTTPStatusError as e:
        raise ScmError(f"GitHub repo lookup failed: {e.response.status_code} "
                       f"{e.response.text[:200]}")
    except Exception as e:
        raise ScmError(f"GitHub repo lookup error: {e}")


def open_pr(repo: RepoCoords, head_branch: str, base_branch: str,
            title: str, body: str, token: Optional[str] = None) -> str:
    """Open a PR head->base; return its html_url. Raises ScmError on failure."""
    if repo.provider != "github":
        raise ScmError(f"unsupported SCM provider: {repo.provider}")
    payload = {"title": title[:250], "head": head_branch, "base": base_branch,
               "body": body[:60000]}
    try:
        r = httpx.post(f"{_GH_API}/repos/{repo.slug}/pulls", json=payload,
                       headers=_gh_headers(token), timeout=45)
        if r.status_code == 422:
            # Most common: a PR for this head already exists — surface its URL.
            existing = _find_existing_pr(repo, head_branch, token=token)
            if existing:
                return existing
            raise ScmError(f"GitHub rejected PR (422): {r.text[:300]}")
        r.raise_for_status()
        return r.json()["html_url"]
    except httpx.HTTPStatusError as e:
        raise ScmError(f"GitHub PR create failed: {e.response.status_code} "
                       f"{e.response.text[:300]}")
    except ScmError:
        raise
    except Exception as e:
        raise ScmError(f"GitHub PR create error: {e}")


def _find_existing_pr(repo: RepoCoords, head_branch: str,
                      token: Optional[str] = None) -> Optional[str]:
    try:
        r = httpx.get(f"{_GH_API}/repos/{repo.slug}/pulls",
                      params={"head": f"{repo.owner}:{head_branch}", "state": "open"},
                      headers=_gh_headers(token), timeout=30)
        r.raise_for_status()
        items = r.json()
        return items[0]["html_url"] if items else None
    except Exception:
        return None


if __name__ == "__main__":
    # Offline self-check: URL parsing (no network).
    assert parse_repo("https://github.com/tejbruhath/VaulS.ai").slug == "tejbruhath/VaulS.ai"
    assert parse_repo("https://github.com/o/r.git").slug == "o/r"
    assert parse_repo("git@github.com:o/r.git").slug == "o/r"
    assert parse_repo("https://x:tok@github.com/o/r.git").slug == "o/r"
    assert parse_repo("https://gitlab.com/o/r.git") is None
    print("scm self-check passed (github URL parsing)")
