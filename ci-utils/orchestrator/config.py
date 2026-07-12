"""Central configuration + per-tool footprints for ci-utils."""
import os

# ---- Tooling -----------------------------------------------------------------
# Deterministic dispatch order: cheapest first (see architecture doc s4.2).
TOOLS = ("gitleaks", "trivy", "sonarqube")

# Per-tool k8s resource footprints. These are the numbers the capacity check
# (architecture doc s4.3) reads against the namespace ResourceQuota, so they
# must reflect real usage rather than a shared flat value.
#   gitleaks    ~150MB   trivy ~300-500MB   sonar-scanner ~512MB+ (JVM)
TOOL_RESOURCES = {
    "gitleaks": {
        "requests": {"cpu": "100m", "memory": "256Mi"},
        "limits": {"cpu": "500m", "memory": "512Mi"},
    },
    "trivy": {
        "requests": {"cpu": "250m", "memory": "512Mi"},
        "limits": {"cpu": "1000m", "memory": "1024Mi"},
    },
    "sonarqube": {
        "requests": {"cpu": "500m", "memory": "768Mi"},
        "limits": {"cpu": "1000m", "memory": "1536Mi"},
    },
}

# Image per tool (the "sonarqube" tool is the sonar-scanner CLI client image).
TOOL_IMAGES = {
    "gitleaks": os.getenv("GITLEAKS_IMAGE", "sast-gitleaks:local"),
    "trivy": os.getenv("TRIVY_IMAGE", "sast-trivy:local"),
    "sonarqube": os.getenv("SONAR_SCANNER_IMAGE", "sast-sonar-scanner:local"),
}

# ---- k8s ---------------------------------------------------------------------
NAMESPACE = os.getenv("SAST_NAMESPACE", "sast")
RESOURCE_QUOTA_NAME = os.getenv("RESOURCE_QUOTA_NAME", "sast-quota")
REPOS_PVC = os.getenv("REPOS_PVC", "sast-repos")
WORKER_NODE_SELECTOR_KEY = os.getenv("WORKER_NODE_SELECTOR_KEY", "sast.aotm/role")
WORKER_NODE_SELECTOR_VAL = os.getenv("WORKER_NODE_SELECTOR_VAL", "worker")
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "180"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

LABEL_JOB_ID = "sast.aotm/job-id"
LABEL_TOOL = "sast.aotm/tool"
LABEL_ATTEMPT = "sast.aotm/attempt"

# ---- Paths / URLs ------------------------------------------------------------
REPOS_DIR = os.getenv("REPOS_DIR", "/repos")
ARTIFACTS_DIR = os.getenv("ARTIFACTS_DIR", "/data/artifacts")
CI_UTILS_URL = os.getenv("CI_UTILS_URL", "http://sast-ci-utils:8080")
SONAR_HOST = os.getenv("SONAR_HOST", "")

# ---- Redis -------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://sast-redis:6379/0")

# ---- Dispatcher --------------------------------------------------------------
DISPATCHER_TICK_SECONDS = float(os.getenv("DISPATCHER_TICK_SECONDS", "2"))
CLONE_TIMEOUT_SECONDS = int(os.getenv("CLONE_TIMEOUT_SECONDS", "300"))

SCHEMA_VERSION = "3.0.0"
