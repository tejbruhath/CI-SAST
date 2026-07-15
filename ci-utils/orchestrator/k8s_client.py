"""
Thin wrapper over the k8s Python client for the scanner Jobs + quota reads.

Only the dispatcher process calls the mutating functions here (create/delete),
so k8s stays a single-writer resource -- no cross-process races on Job objects.
"""
import logging  # Log config load mode and API failures.
import re  # Parse Kubernetes memory quantity strings.
from typing import Dict, Optional, Tuple  # Type hints for API clients and quota maps.

from kubernetes import client, config as kube_config  # Official k8s client + kubeconfig loaders.
from kubernetes.client.rest import ApiException  # HTTP errors from the k8s API server.

from . import config  # Namespace, images, labels, and resource footprints.

logger = logging.getLogger("orchestrator.k8s")  # Logger scoped to this k8s wrapper.

_batch: Optional[client.BatchV1Api] = None  # Lazy Batch API client for Jobs.
_core: Optional[client.CoreV1Api] = None  # Lazy Core API client for ResourceQuota.


def init() -> None:  # Load kube credentials and construct API clients once.
    global _batch, _core  # Assign module-level singletons.
    try:
        kube_config.load_incluster_config()  # Prefer ServiceAccount when inside a pod.
        logger.info("Loaded in-cluster k8s config")  # Running on the cluster path.
    except Exception:
        kube_config.load_kube_config()  # Fall back to ~/.kube/config for local dev.
        logger.info("Loaded local kubeconfig")  # Dev machine talking to the cluster.
    _batch = client.BatchV1Api()  # Client for Job create/list/delete.
    _core = client.CoreV1Api()  # Client for ResourceQuota reads.


def batch() -> client.BatchV1Api:  # Accessor that auto-inits if needed.
    if _batch is None:
        init()  # First use initializes clients transparently.
    return _batch  # Shared BatchV1Api instance.


def core() -> client.CoreV1Api:  # Accessor for CoreV1 operations.
    if _core is None:
        init()  # Ensure clients exist before first Core API call.
    return _core  # Shared CoreV1Api instance.


# ---- resource-quantity parsing ----------------------------------------------
def cpu_to_millicores(q: str) -> float:  # Normalize CPU strings for arithmetic.
    if q is None:
        return 0.0  # Missing quantity counts as zero usage.
    q = str(q)  # Coerce numeric inputs to string for endswith checks.
    if q.endswith("m"):  # Already millicores (e.g. "100m").
        return float(q[:-1])  # Strip the trailing 'm' unit.
    return float(q) * 1000.0  # Whole cores become millicores (1 → 1000).


_MEM_UNITS = {  # Multipliers for k8s binary and decimal memory suffixes.
    "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,  # Power-of-two units.
    "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4,  # Decimal SI units.
}


def mem_to_bytes(q: str) -> float:  # Normalize memory quantities to raw bytes.
    if q is None:
        return 0.0  # Treat missing as zero.
    q = str(q)  # Ensure regex can match string form.
    m = re.match(r"^(\d+(?:\.\d+)?)([KMGT]i?)?$", q)  # Number + optional unit.
    if not m:
        return 0.0  # Unparseable quantities become zero safely.
    val, unit = m.group(1), m.group(2)  # Capture groups for amount and suffix.
    return float(val) * (_MEM_UNITS.get(unit, 1) if unit else 1)  # Scale by unit or plain bytes.


# ---- job naming --------------------------------------------------------------
def job_name(tool: str, job_id: str, attempt: int) -> str:  # Deterministic Job object name.
    tool_label = "sonar-scanner" if tool == "sonarqube" else tool  # Friendlier image-aligned label.
    return f"sast-{tool_label}-{job_id}-{attempt}"  # Unique per tool/job/attempt triple.


# ---- job construction --------------------------------------------------------
def build_job(tool: str, job_id: str, project_key: str, sonar_token: str,
              attempt: int) -> client.V1Job:  # Build a V1Job body without creating it yet.
    name = job_name(tool, job_id, attempt)  # k8s object name for this attempt.
    res = config.TOOL_RESOURCES[tool]  # Request/limit footprint for capacity checks.

    env = [  # Environment variables injected into the scanner container.
        client.V1EnvVar(name="JOB_ID", value=job_id),  # Correlate callbacks to this job.
        client.V1EnvVar(name="REPO_PATH", value=f"{config.REPOS_DIR}/{job_id}"),  # Cloned workspace path.
        client.V1EnvVar(name="CI_UTILS_URL", value=config.CI_UTILS_URL),  # Where to POST results.
    ]
    if tool == "sonarqube":  # Sonar-only credentials and host configuration.
        env += [
            client.V1EnvVar(name="SONAR_PROJECT_KEY", value=project_key),  # Target Sonar project.
            client.V1EnvVar(name="SONAR_TOKEN", value=sonar_token),  # Auth token for Sonar API.
            client.V1EnvVar(name="SONAR_HOST", value=config.SONAR_HOST),  # Sonar server base URL.
        ]

    volume_mounts = [client.V1VolumeMount(name="repos", mount_path=config.REPOS_DIR)]  # Mount shared PVC.
    volumes = [client.V1Volume(  # Volume definition backed by the repos PVC.
        name="repos",
        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
            claim_name=config.REPOS_PVC),  # Claim name from config.
    )]

    container = client.V1Container(  # Single scanner container for this Job.
        name=name,  # Container name mirrors Job name for log clarity.
        image=config.TOOL_IMAGES[tool],  # Image for this tool from config/env.
        image_pull_policy="IfNotPresent",  # Prefer local image; avoid always-pull cost.
        env=env,  # Pass job context and optional Sonar vars.
        volume_mounts=volume_mounts,  # Attach the shared repos volume.
        resources=client.V1ResourceRequirements(
            requests=res["requests"], limits=res["limits"]),  # Quota-aware resource box.
    )

    labels = {  # Labels enable list/filter by job_id and tool.
        "app": "sast-scan",  # Common app label for selectors.
        config.LABEL_JOB_ID: job_id,  # Which scan this Job belongs to.
        config.LABEL_TOOL: tool,  # Which scanner tool this Job runs.
        config.LABEL_ATTEMPT: str(attempt),  # Retry attempt encoded as string.
    }

    template = client.V1PodTemplateSpec(  # Pod template embedded in the Job spec.
        metadata=client.V1ObjectMeta(labels=labels),  # Pod inherits the same labels.
        spec=client.V1PodSpec(
            restart_policy="Never",  # Fail the Job; do not restart the pod.
            node_selector={config.WORKER_NODE_SELECTOR_KEY: config.WORKER_NODE_SELECTOR_VAL},  # Pin to workers.
            containers=[container],  # One scanner container only.
            volumes=volumes,  # Attach PVC volume definition.
        ),
    )

    spec = client.V1JobSpec(
        template=template,  # Pod template for each Job attempt.
        backoff_limit=0,                       # no k8s retries; dispatcher owns retry
        ttl_seconds_after_finished=config.JOB_TTL_SECONDS,  # safety-net cleanup only
    )

    return client.V1Job(  # Fully specified Job object ready for create.
        api_version="batch/v1", kind="Job",  # Standard batch Job kind.
        metadata=client.V1ObjectMeta(name=name, namespace=config.NAMESPACE, labels=labels),
        spec=spec,  # Spec constructed above with template and TTL.
    )


def create_job(job: client.V1Job) -> None:  # Submit a built Job to the API server.
    batch().create_namespaced_job(namespace=config.NAMESPACE, body=job)  # Create in SAST namespace.


def delete_job(name: str) -> None:  # Best-effort delete of a finished or failed Job.
    try:
        batch().delete_namespaced_job(
            name=name, namespace=config.NAMESPACE,
            body=client.V1DeleteOptions(propagation_policy="Background"),  # Cascade delete pods async.
        )
    except ApiException as exc:
        if exc.status != 404:  # 404 is fine: already gone.
            logger.warning("delete_job %s failed: %s", name, exc)  # Log unexpected failures.


def job_phase(job_id: str, tool: str) -> str:
    """Return 'active' | 'succeeded' | 'failed' | 'absent' for the newest
    attempt of (job_id, tool)."""
    selector = f"{config.LABEL_JOB_ID}={job_id},{config.LABEL_TOOL}={tool}"  # Label filter string.
    try:
        jobs = batch().list_namespaced_job(
            namespace=config.NAMESPACE, label_selector=selector).items  # All attempts for pair.
    except ApiException as exc:
        logger.warning("list jobs for %s/%s failed: %s", job_id, tool, exc)
        return "absent"  # Treat list errors as missing for safety.
    if not jobs:
        return "absent"  # No Job objects match the selector.
    # newest attempt wins
    def attempt_of(j):  # Extract attempt label as int for max() key.
        try:
            return int(j.metadata.labels.get(config.LABEL_ATTEMPT, "0"))  # Default attempt 0.
        except Exception:
            return 0  # Bad labels sort as oldest.
    j = max(jobs, key=attempt_of)  # Pick the highest attempt number.
    st = j.status  # Job status subresource from the API.
    if st and st.failed:  # Pod failed at least once (with backoff_limit=0).
        return "failed"
    if st and st.succeeded:  # At least one successful pod completion.
        return "succeeded"
    return "active"  # Created or still running.


# ---- quota -------------------------------------------------------------------
def read_quota() -> Tuple[Dict[str, float], Dict[str, float]]:
    """Return (hard, used) in normalized units: cpu=millicores, memory=bytes,
    for BOTH requests.* and limits.* quota dimensions (keys: requests_cpu,
    requests_memory, limits_cpu, limits_memory). Missing keys -> unlimited
    (float('inf')) for hard, 0 for used.

    Checking only requests.* here previously let the dispatcher happily
    approve a dispatch that fit the requests quota but blew the SEPARATE
    limits.cpu/limits.memory quota dimension -- k8s's own admission control
    then rejected the pod forever (FailedCreate, retried indefinitely by the
    job-controller), and since the Job never got a pod, ci-utils' own
    job_phase() never saw it as failed either (Job.status.failed only
    increments on an actual pod failure, not an admission rejection) -- so it
    just sat "active" with zero progress, invisible to the retry/give-up path.
    """
    dims = ("requests.cpu", "requests.memory", "limits.cpu", "limits.memory")  # All quota axes.
    hard = {d: float("inf") for d in dims}  # Default: unlimited if quota missing.
    used = {d: 0.0 for d in dims}  # Default: zero usage if fields absent.
    try:
        q = core().read_namespaced_resource_quota(
            name=config.RESOURCE_QUOTA_NAME, namespace=config.NAMESPACE)  # Fetch quota object.
    except ApiException as exc:
        if exc.status == 404:  # No quota configured: treat as unlimited.
            logger.debug("ResourceQuota %s not found; treating as unlimited",
                         config.RESOURCE_QUOTA_NAME)
        else:
            logger.warning("read quota failed: %s", exc)  # Other API errors still fail open.
        return hard, used  # Caller proceeds without hard capacity gates.

    h = (q.status.hard or {}) if q.status else {}  # Hard ceilings from quota status.
    u = (q.status.used or {}) if q.status else {}  # Observed usage from quota status.
    for d in dims:  # Normalize each dimension into millicores or bytes.
        conv = mem_to_bytes if d.endswith("memory") else cpu_to_millicores  # Pick converter.
        if d in h:
            hard[d] = conv(h[d])  # Convert hard limit string to number.
        used[d] = conv(u.get(d, "0"))  # Convert used amount (default zero).
    return hard, used  # Pair of maps for capacity gating in the dispatcher.
