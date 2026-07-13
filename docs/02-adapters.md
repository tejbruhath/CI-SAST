---
title: Scanner adapters
source:
  - ci-utils/sentriq/adapters/base.py
  - ci-utils/sentriq/adapters/__init__.py
  - ci-utils/sentriq/adapters/gitleaks.py
  - ci-utils/sentriq/adapters/semgrep.py
  - ci-utils/sentriq/adapters/trivy.py
  - ci-utils/sentriq/adapters/zap.py
  - ci-utils/sentriq/adapters/nuclei.py
---

# Scanner adapters

> Normalise every security scanner behind a single interface so the executor can run any tool and receive the same `Finding` objects.

## Role in the pipeline

Adapters sit between the raw scanner tools and the rest of Sentriq. The [orchestrator](07-orchestration.md) asks the registry for scanners by pipeline, the [executor](03-executor.md) calls `command()` and runs the Docker container, then calls `parse()` on the tool-native output. The [aggregator](04-aggregator.md) downstream only ever sees validated `Finding` objects, so it does not need per-tool knowledge.

## How it works

Each adapter is a `BaseAdapter` subclass that owns one tool end to end. It declares the Docker image, whether it is `STATIC` (source-code scan) or `DYNAMIC` (live-target scan), where inside the container the work directory is mounted, and how the scanner writes its native report. Two methods complete the contract:

* `command(target, workdir)` — returns the argv passed to the container. It must only rely on the mounted `workdir` and the `target`.
* `parse(raw_output, target)` — takes the contents of `OUTPUT_FILE` and returns `list[Finding]`. It is pure: no Docker, no I/O, no network.

Adapters are discovered automatically. A class-level `@register` decorator instantiates the adapter and stores it in `REGISTRY` under `cls.NAME`. Importing `ci-utils/sentriq/adapters/__init__.py` imports every adapter module in order, which triggers the registrations.

The five built-in adapters cover:

| Tool | Image | Pipeline | Finding type |
|------|-------|----------|--------------|
| gitleaks | `zricethezav/gitleaks:latest` | `STATIC` | secret |
| semgrep | `semgrep/semgrep:latest` | `STATIC` | sast |
| trivy | `aquasec/trivy:latest` | `STATIC` | vulnerability |
| zap | `ghcr.io/zaproxy/zaproxy:stable` | `DYNAMIC` | dast |
| nuclei | `projectdiscovery/nuclei:latest` | `DYNAMIC` | dast or vulnerability |

Static adapters receive a cloned repository path as `target` and scan the mounted `workdir`. Dynamic adapters receive a URL as `target` and attack that endpoint. Each parser maps its tool's native JSON or JSONL fields to the shared [Finding schema](01-schema.md), stripping container work-dir prefixes, normalising severities, and building deterministic fingerprints.

## Code walkthrough

The base contract in `ci-utils/sentriq/adapters/base.py` defines what every subclass must provide:

```python
class BaseAdapter:
    # ---- subclasses MUST set these ----
    NAME: str = ""                 # "gitleaks" | "semgrep" | "trivy" | "zap" | "nuclei"
    IMAGE: str = ""                # docker image ref
    PIPELINE: str = STATIC         # STATIC or DYNAMIC
    # File (relative to the container work dir) the tool writes native output to.
    OUTPUT_FILE: str = "output.json"
    # Where the executor bind-mounts the work dir INSIDE the container. Most
    # tools honour an explicit path; ZAP always writes its report to /zap/wrk,
    # so its adapter overrides this. The executor mounts the host work dir here
    # and reads OUTPUT_FILE back out of it.
    MOUNT: str = "/work"

    def command(self, target: str, workdir: str) -> List[str]:
        """Return the container argv.

        static tools: `target` is the path to the cloned repo (mounted at
          `workdir` inside the container); scan there and write OUTPUT_FILE.
        dynamic tools: `target` is the URL under test; write OUTPUT_FILE into
          `workdir`.
        Must NOT depend on host state — only the mounted workdir + target.
        """
        raise NotImplementedError

    def parse(self, raw_output: str, target: str) -> List[Finding]:
        """Convert the tool's native output (contents of OUTPUT_FILE) into
        Findings. Pure: no I/O, no Docker. `target` is passed so dynamic
        adapters can record the scanned URL. Return [] on empty/no findings."""
        raise NotImplementedError
```

`NAME`, `IMAGE`, `PIPELINE`, `OUTPUT_FILE`, and `MOUNT` are declared at the class level so the executor can schedule the container before it ever invokes `command()`. `command()` and `parse()` are the only runtime behaviour an adapter implements.

Registration is a small class decorator that instantiates and stores the adapter:

```python
REGISTRY: Dict[str, BaseAdapter] = {}


def register(cls: Type[BaseAdapter]) -> Type[BaseAdapter]:
    """Class decorator: instantiate + register an adapter under its NAME."""
    if not cls.NAME:
        raise ValueError(f"{cls.__name__} must set NAME")
    REGISTRY[cls.NAME] = cls()
    return cls
```

`__init__.py` imports the modules in a fixed order so the registry is populated deterministically. The comments note that import order also serves as dispatch order, cheapest and fastest scanners first:

```python
from .base import BaseAdapter, REGISTRY, register, get, for_pipeline  # noqa: F401

# Import order = deterministic dispatch order (cheapest/fastest first).
from . import gitleaks   # noqa: F401,E402  static: secrets
from . import semgrep    # noqa: F401,E402  static: SAST
from . import trivy      # noqa: F401,E402  static: SCA/CVE
from . import zap        # noqa: F401,E402  dynamic: DAST baseline
from . import nuclei     # noqa: F401,E402  dynamic: template CVE/misconfig
```

The gitleaks adapter shows a typical static scanner. It runs in `no-git` mode so it works on any checked-out tree, and forces exit code `0` because findings are not a run failure:

```python
@register
class GitleaksAdapter(BaseAdapter):
    NAME = "gitleaks"
    IMAGE = "zricethezav/gitleaks:latest"
    PIPELINE = STATIC
    OUTPUT_FILE = "output.json"

    def command(self, target: str, workdir: str) -> List[str]:
        # --no-git: scan the working tree as files (works on shallow clones and
        # non-repo dirs alike). --exit-code 0: findings are not a run failure.
        return [
            "detect",
            f"--source={workdir}",
            "--no-git",
            "--report-format=json",
            f"--report-path={workdir}/{self.OUTPUT_FILE}",
            "--exit-code=0",
        ]
```

Its parser turns each gitleaks hit into a `Finding`, bumping cloud-provider and private-key rules to `critical` and computing a stable fingerprint from `rule:file:line` rather than gitleaks' own scan-time fingerprint:

```python
    def parse(self, raw_output: str, target: str) -> List[Finding]:
        ...
        for f in data:
            ...
            rule = f.get("RuleID", "unknown")
            crit = any(k in rule.lower() for k in _CRITICAL_KEYWORDS)
            file = _rel(f.get("File", "unknown"))
            line = f.get("StartLine")
            out.append(Finding(
                tool=self.NAME, pipeline=STATIC, type="secret",
                severity="critical" if crit else "high",
                rule_id=rule,
                message=f"Secret detected: {rule} in {file}:{line}",
                file=file, line=line, url=None,
                details={"secret_type": rule, "entropy": f.get("Entropy"),
                         "match": f.get("Match", "")[:80]},
                fingerprint=f"gitleaks:{rule}:{file}:{line}",
            ))
```

The semgrep adapter parses the Semgrep JSON report, maps Semgrep's `ERROR`/`WARNING`/`INFO` severities to `high`/`medium`/`low`, strips the `/work/` prefix from paths, and extracts CWE, OWASP, category, and references from rule metadata:

```python
        severity = self._map_severity(extra.get("severity") if isinstance(extra, dict) else None)
        message = self._truncate(extra.get("message", "") if isinstance(extra, dict) else "", 200)
        references = metadata.get("references") if isinstance(metadata, dict) else None
        url = references[0] if isinstance(references, list) and references else None
```

Trivy runs only the vulnerability scanner (`--scanners vuln`) and emits one `Finding` per CVE. It pulls package name, installed and fixed versions, CVSS v3 score, package type, and CWE IDs into `details`:

```python
                out.append(Finding(
                    tool=self.NAME, pipeline=STATIC, type="vulnerability",
                    severity=_TRIVY_SEV.get(v.get("Severity", "UNKNOWN"), "low"),
                    rule_id=vid,
                    message=f"{pkg}: {title[:120]}",
                    file=file, line=None, url=v.get("PrimaryURL"),
                    details={
                        "package_name": pkg,
                        "installed_version": v.get("InstalledVersion"),
                        "fixed_version": v.get("FixedVersion"),
                        "cvss_score": cvss,
                        "pkg_type": pkg_type,
                        "cwe": v.get("CweIDs", []),
                    },
                    fingerprint=f"trivy:{vid}:{file}:{pkg}",
                ))
```

ZAP is dynamic and has the most visible quirk: `zap-baseline.py` always writes its JSON report to `/zap/wrk`, so the adapter overrides `MOUNT`:

```python
@register
class ZapAdapter(BaseAdapter):
    NAME = "zap"
    IMAGE = "ghcr.io/zaproxy/zaproxy:stable"
    PIPELINE = DYNAMIC
    OUTPUT_FILE = "output.json"
    MOUNT = "/zap/wrk"  # zap-baseline.py always writes its -J report here

    def command(self, target: str, workdir: str) -> List[str]:
        return ["zap-baseline.py", "-t", target, "-J", self.OUTPUT_FILE, "-I"]
```

The parser walks the ZAP JSON report, collects up to ten affected URIs per alert, and maps ZAP's numeric `riskcode` to severities. The fingerprint is built from `zap:pluginid:host`.

Nuclei writes JSONL output. The parser classifies a finding as `vulnerability` when the template reports CVE IDs, otherwise as `dast`, and uses `matched-at` (or `host`) as the file location:

```python
            cve_ids = classification.get("cve-id") or []
            finding_type = "vulnerability" if cve_ids else "dast"
```

## Diagram

The registry builds itself at import time, then the executor uses it at runtime.

```mermaid
flowchart LR
    subgraph "Import time"
        A[gitleaks.py<br/>@register] --> R[REGISTRY]
        B[semgrep.py<br/>@register] --> R
        C[trivy.py<br/>@register] --> R
        D[zap.py<br/>@register] --> R
        E[nuclei.py<br/>@register] --> R
    end

    subgraph "Runtime"
        O[Orchestrator] -->|for_pipeline| R
        R -->|get(name)| Ad[Adapter instance]
        Ad -->|command(target, workdir)| Cmd[argv]
        Cmd -->|docker run| Docker[Container]
        Docker -->|writes| OF[OUTPUT_FILE<br/>under MOUNT]
        OF -->|raw string| Ad
        Ad -->|parse(raw_output, target)| F[Finding objects]
    end
```

## Key decisions & gotchas

* Adapters are pure after `command()`. `parse()` never shells out, which makes unit tests as simple as feeding a sample JSON string.
* The executor owns Docker, mounts, and timeouts; adapters only describe *what* to run and *how* to read the output.
* `MOUNT` is usually `/work`, but ZAP requires `/zap/wrk`. The executor must read `OUTPUT_FILE` relative to the adapter's `MOUNT`, not assume `/work`.
* ZAP's `command()` does not include `workdir` in the argv; it relies on `zap-baseline.py` writing to its fixed `/zap/wrk` directory. The executor still mounts the host work dir there so the report can be read back.
* Nuclei uses `output.jsonl` (one JSON object per line), while the other adapters use `output.json`.
* Static scanners strip the container work-dir prefix from paths so `file` is relative to the repository root.
* Severity mappings are adapter-specific because every scanner uses its own taxonomy.
* Import order in `__init__.py` is the dispatch order. Keep fast scanners first to fail cheaply.
* Adding a scanner means: create a module under `adapters/`, subclass `BaseAdapter`, set the five class attributes, implement `command()` and `parse()`, decorate the class with `@register`, and import the module in `__init__.py`.

## Related docs

- [01-schema.md](01-schema.md) — the `Finding` object every adapter produces.
- [03-executor.md](03-executor.md) — runs the Docker container using `command()` and feeds the output to `parse()`.
- [04-aggregator.md](04-aggregator.md) — consumes the normalised findings returned by adapters.
- [07-orchestration.md](07-orchestration.md) — decides which pipeline to run and which adapters to ask for.
