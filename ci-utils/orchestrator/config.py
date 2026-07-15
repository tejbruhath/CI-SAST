"""Central configuration + per-tool footprints for ci-utils."""
import os  # All tunables come from environment variables with safe defaults.

# ---- Tooling -----------------------------------------------------------------
# Deterministic dispatch order: cheapest first (see architecture doc s4.2).
TOOLS = ("gitleaks", "trivy", "sonarqube")  # Fixed tool order; cheaper scanners first.

# Per-tool k8s resource footprints. These are the numbers the capacity check
# (architecture doc s4.3) reads against the namespace ResourceQuota, so they
# must reflect real usage rather than a shared flat value.
#   gitleaks    ~150MB   trivy ~300-500MB   sonar-scanner ~512MB+ (JVM)
TOOL_RESOURCES = {  # CPU/memory requests and limits per scanner tool.
    "gitleaks": {
        "requests": {"cpu": "100m", "memory": "256Mi"},  # Guaranteed scheduling floor.
        "limits": {"cpu": "500m", "memory": "512Mi"},  # Hard cap to protect the node.
    },
    "trivy": {
        "requests": {"cpu": "250m", "memory": "512Mi"},  # Trivy needs more RAM for DBs.
        "limits": {"cpu": "500m", "memory": "768Mi"},  # Cap so quota math stays honest.
    },
    "sonarqube": {
        "requests": {"cpu": "500m", "memory": "768Mi"},  # JVM scanner is the heaviest.
        "limits": {"cpu": "750m", "memory": "1200Mi"},  # Higher ceiling for analysis peaks.
    },
}

# Image per tool (the "sonarqube" tool is the sonar-scanner CLI client image).
TOOL_IMAGES = {  # Container image names pulled when creating k8s Jobs.
    "gitleaks": os.getenv("GITLEAKS_IMAGE", "sast-gitleaks:local"),  # Secret-scanning image.
    "trivy": os.getenv("TRIVY_IMAGE", "sast-trivy:local"),  # Vulnerability-scanning image.
    "sonarqube": os.getenv("SONAR_SCANNER_IMAGE", "sast-sonar-scanner:local"),  # Sonar CLI image.
}

# ---- k8s ---------------------------------------------------------------------
NAMESPACE = os.getenv("SAST_NAMESPACE", "sast")  # Kubernetes namespace for scan Jobs.
RESOURCE_QUOTA_NAME = os.getenv("RESOURCE_QUOTA_NAME", "sast-quota")  # Quota object the dispatcher reads.
REPOS_PVC = os.getenv("REPOS_PVC", "sast-repos")  # PVC shared so scanners see cloned repos.
WORKER_NODE_SELECTOR_KEY = os.getenv("WORKER_NODE_SELECTOR_KEY", "sast.aotm/role")  # Node label key for workers.
WORKER_NODE_SELECTOR_VAL = os.getenv("WORKER_NODE_SELECTOR_VAL", "worker")  # Node label value for workers.
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "180"))  # Auto-delete finished Jobs after this.
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))  # How many tool attempts before giving up.

LABEL_JOB_ID = "sast.aotm/job-id"  # k8s label tying a Job to our job_id.
LABEL_TOOL = "sast.aotm/tool"  # k8s label naming which scanner tool ran.
LABEL_ATTEMPT = "sast.aotm/attempt"  # k8s label for retry attempt number.

# ---- Paths / URLs ------------------------------------------------------------
REPOS_DIR = os.getenv("REPOS_DIR", "/repos")  # Host/mount path where clones live.
ARTIFACTS_DIR = os.getenv("ARTIFACTS_DIR", "/data/artifacts")  # Where mega-artifact.json is written.
CI_UTILS_URL = os.getenv("CI_UTILS_URL", "http://sast-ci-utils:8080")  # Callback base URL for scanners.
SONAR_HOST = os.getenv("SONAR_HOST", "")  # SonarQube server URL for issue deep links.

# ---- Redis -------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://sast-redis:6379/0")  # Job state and event bus backend.
CLONE_TIMEOUT_SECONDS = int(os.getenv("CLONE_TIMEOUT_SECONDS", "300"))  # Abort slow git clones after 5m.

# ---- Dispatcher --------------------------------------------------------------
DISPATCHER_TICK_SECONDS = float(os.getenv("DISPATCHER_TICK_SECONDS", "2"))  # blpop timeout / loop period.

SCHEMA_VERSION = "3.0.0"  # Version string stamped into mega-artifact metadata.
