"""Central configuration for the Sentriq backend (env-driven)."""
import os

# ---- scan execution ----------------------------------------------------------
# Shared data root. MUST be bind-mounted at the identical path host<->worker so
# nested `docker run -v` paths resolve on the host daemon (see executor.py).
SENTRIQ_DATA_DIR = os.getenv("SENTRIQ_DATA_DIR", "/data")
REPOS_DIR = os.path.join(SENTRIQ_DATA_DIR, "repos")

CLONE_TIMEOUT_SECONDS = int(os.getenv("CLONE_TIMEOUT_SECONDS", "300"))
# Token for cloning private repos AND pushing fix PRs (GitHub/GitLab PAT).
GIT_TOKEN = os.getenv("SENTRIQ_GIT_TOKEN", "")
TOOL_TIMEOUT_SECONDS = int(os.getenv("TOOL_TIMEOUT_SECONDS", "900"))
# docker network for dynamic (DAST) scanners. "host" reaches localhost/staging
# on Linux; use "bridge" for scanning public URLs only.
SCANNER_NETWORK = os.getenv("SCANNER_NETWORK", "host")

# ---- DeepSeek LLM ------------------------------------------------------------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
# deepseek-v4-flash is the current fast model; legacy deepseek-chat deprecates
# 2026-07-24, so we pin the v4 id.
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_TIMEOUT_SECONDS = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "120"))
# Master switch: when false, triage/fix stages are skipped (findings still
# stored). Lets the pipeline run tool-only without burning tokens.
LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() == "true"
# Only run expensive fix-generation for findings at/above this severity.
FIX_MIN_SEVERITY = os.getenv("FIX_MIN_SEVERITY", "high")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
