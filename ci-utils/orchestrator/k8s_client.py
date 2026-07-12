"""
Thin wrapper over the k8s Python client for the scanner Jobs + quota reads.

Only the dispatcher process calls the mutating functions here (create/delete),
so k8s stays a single-writer resource -- no cross-process races on Job objects.
"""
import logging
import re
from typing import Dict, Optional, Tuple

from kubernetes import client, config as kube_config
from kubernetes.client.rest import ApiException

from . import config

logger = logging.getLogger("orchestrator.k8s")

_batch: Optional[client.BatchV1Api] = None
_core: Optional[client.CoreV1Api] = None


def init() -> None:
    global _batch, _core
    try:
        kube_config.load_incluster_config()
        logger.info("Loaded in-cluster k8s config")
    except Exception:
        kube_config.load_kube_config()
        logger.info("Loaded local kubeconfig")
    _batch = client.BatchV1Api()
    _core = client.CoreV1Api()


def batch() -> client.BatchV1Api:
    if _batch is None:
        init()
    return _batch


def core() -> client.CoreV1Api:
    if _core is None:
        init()
    return _core


# ---- resource-quantity parsing ----------------------------------------------
def cpu_to_millicores(q: str) -> float:
    if q is None:
        return 0.0
    q = str(q)
    if q.endswith("m"):
        return float(q[:-1])
    return float(q) * 1000.0


_MEM_UNITS = {
    "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
    "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4,
}


def mem_to_bytes(q: str) -> float:
    if q is None:
        return 0.0
    q = str(q)
    m = re.match(r"^(\d+(?:\.\d+)?)([KMGT]i?)?$", q)
    if not m:
        return 0.0
    val, unit = m.group(1), m.group(2)
    return float(val) * (_MEM_UNITS.get(unit, 1) if unit else 1)


# ---- job naming --------------------------------------------------------------
def job_name(tool: str, job_id: str, attempt: int) -> str:
    tool_label = "sonar-scanner" if tool == "sonarqube" else tool
    return f"sast-{tool_label}-{job_id}-{attempt}"


# ---- job construction --------------------------------------------------------
def build_job(tool: str, job_id: str, project_key: str, sonar_token: str,
              attempt: int) -> client.V1Job:
    name = job_name(tool, job_id, attempt)
    res = config.TOOL_RESOURCES[tool]

    env = [
        client.V1EnvVar(name="JOB_ID", value=job_id),
        client.V1EnvVar(name="REPO_PATH", value=f"{config.REPOS_DIR}/{job_id}"),
        client.V1EnvVar(name="CI_UTILS_URL", value=config.CI_UTILS_URL),
    ]
    if tool == "sonarqube":
        env += [
            client.V1EnvVar(name="SONAR_PROJECT_KEY", value=project_key),
            client.V1EnvVar(name="SONAR_TOKEN", value=sonar_token),
            client.V1EnvVar(name="SONAR_HOST", value=config.SONAR_HOST),
        ]

    volume_mounts = [client.V1VolumeMount(name="repos", mount_path=config.REPOS_DIR)]
    volumes = [client.V1Volume(
        name="repos",
        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
            claim_name=config.REPOS_PVC),
    )]

    container = client.V1Container(
        name=name,
        image=config.TOOL_IMAGES[tool],
        image_pull_policy="IfNotPresent",
        env=env,
        volume_mounts=volume_mounts,
        resources=client.V1ResourceRequirements(
            requests=res["requests"], limits=res["limits"]),
    )

    labels = {
        "app": "sast-scan",
        config.LABEL_JOB_ID: job_id,
        config.LABEL_TOOL: tool,
        config.LABEL_ATTEMPT: str(attempt),
    }

    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels=labels),
        spec=client.V1PodSpec(
            restart_policy="Never",
            node_selector={config.WORKER_NODE_SELECTOR_KEY: config.WORKER_NODE_SELECTOR_VAL},
            containers=[container],
            volumes=volumes,
        ),
    )

    spec = client.V1JobSpec(
        template=template,
        backoff_limit=0,                       # no k8s retries; dispatcher owns retry
        ttl_seconds_after_finished=config.JOB_TTL_SECONDS,  # safety-net cleanup only
    )

    return client.V1Job(
        api_version="batch/v1", kind="Job",
        metadata=client.V1ObjectMeta(name=name, namespace=config.NAMESPACE, labels=labels),
        spec=spec,
    )


def create_job(job: client.V1Job) -> None:
    batch().create_namespaced_job(namespace=config.NAMESPACE, body=job)


def delete_job(name: str) -> None:
    try:
        batch().delete_namespaced_job(
            name=name, namespace=config.NAMESPACE,
            body=client.V1DeleteOptions(propagation_policy="Background"),
        )
    except ApiException as exc:
        if exc.status != 404:
            logger.warning("delete_job %s failed: %s", name, exc)


def job_phase(job_id: str, tool: str) -> str:
    """Return 'active' | 'succeeded' | 'failed' | 'absent' for the newest
    attempt of (job_id, tool)."""
    selector = f"{config.LABEL_JOB_ID}={job_id},{config.LABEL_TOOL}={tool}"
    try:
        jobs = batch().list_namespaced_job(
            namespace=config.NAMESPACE, label_selector=selector).items
    except ApiException as exc:
        logger.warning("list jobs for %s/%s failed: %s", job_id, tool, exc)
        return "absent"
    if not jobs:
        return "absent"
    # newest attempt wins
    def attempt_of(j):
        try:
            return int(j.metadata.labels.get(config.LABEL_ATTEMPT, "0"))
        except Exception:
            return 0
    j = max(jobs, key=attempt_of)
    st = j.status
    if st and st.failed:
        return "failed"
    if st and st.succeeded:
        return "succeeded"
    return "active"


# ---- quota -------------------------------------------------------------------
def read_quota() -> Tuple[Dict[str, float], Dict[str, float]]:
    """Return (hard, used) in normalized units: cpu=millicores, memory=bytes.
    Missing keys -> treated as unlimited (float('inf')) for hard, 0 for used."""
    hard = {"cpu": float("inf"), "memory": float("inf")}
    used = {"cpu": 0.0, "memory": 0.0}
    try:
        q = core().read_namespaced_resource_quota(
            name=config.RESOURCE_QUOTA_NAME, namespace=config.NAMESPACE)
    except ApiException as exc:
        if exc.status == 404:
            logger.debug("ResourceQuota %s not found; treating as unlimited",
                         config.RESOURCE_QUOTA_NAME)
        else:
            logger.warning("read quota failed: %s", exc)
        return hard, used

    h = (q.status.hard or {}) if q.status else {}
    u = (q.status.used or {}) if q.status else {}
    if "requests.cpu" in h:
        hard["cpu"] = cpu_to_millicores(h["requests.cpu"])
    if "requests.memory" in h:
        hard["memory"] = mem_to_bytes(h["requests.memory"])
    used["cpu"] = cpu_to_millicores(u.get("requests.cpu", "0"))
    used["memory"] = mem_to_bytes(u.get("requests.memory", "0"))
    return hard, used
