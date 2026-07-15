"""Central configuration for the Sentriq backend (env-driven)."""
import os  # read environment variables for deploy-time config

# ---- scan execution ----------------------------------------------------------
# TODO: SENTRIQ_DATA_DIR must match host path so nested docker -v mounts resolve.
SENTRIQ_DATA_DIR = os.getenv("SENTRIQ_DATA_DIR") or os.getenv("HOST_DATA_DIR", "/data")  # shared data root
REPOS_DIR = os.path.join(SENTRIQ_DATA_DIR, "repos")  # where cloned git repos live

CLONE_TIMEOUT_SECONDS = int(os.getenv("CLONE_TIMEOUT_SECONDS", "300"))  # max seconds for git clone
# Token for cloning private repos AND pushing fix PRs (GitHub/GitLab PAT).
GIT_TOKEN = os.getenv("SENTRIQ_GIT_TOKEN", "")  # optional PAT for private git access
TOOL_TIMEOUT_SECONDS = int(os.getenv("TOOL_TIMEOUT_SECONDS", "900"))  # max seconds per scanner container
# docker network for dynamic (DAST) scanners. "host" reaches localhost/staging
# on Linux; use "bridge" for scanning public URLs only.
SCANNER_NETWORK = os.getenv("SCANNER_NETWORK", "host")  # docker network mode for DAST tools

# ---- DeepSeek LLM ------------------------------------------------------------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")  # API key for DeepSeek LLM calls
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")  # DeepSeek API base URL
# deepseek-v4-flash is the current fast model; legacy deepseek-chat deprecates
# 2026-07-24, so we pin the v4 id.
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")  # model id used for triage/fix
DEEPSEEK_TIMEOUT_SECONDS = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "120"))  # HTTP timeout for LLM requests
# Master switch: when false, triage/fix stages are skipped (findings still
# stored). Lets the pipeline run tool-only without burning tokens.
LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() == "true"  # toggle AI triage and fix generation
# NOTE: the fix-generation severity floor is per-scan (Scan.auto_fix_severity,
# chosen in the UI), not a global env knob.

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # Celery/broker Redis connection URL
