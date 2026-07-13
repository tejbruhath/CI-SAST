"""
Scanner adapter interface — the contract every tool integration implements.

An adapter owns ONE tool end to end and nothing else:
  * `IMAGE`     — the Docker image the executor runs.
  * `PIPELINE`  — STATIC (scans source) or DYNAMIC (scans a live target).
  * `command()` — the argv the container runs; writes tool-native output to a
                  known file under the mounted work dir.
  * `parse()`   — reads that native output and returns a list[Finding].

The executor (sentriq/executor.py) handles running the container, mounting the
target, timeouts, and capturing output — adapters never shell out themselves.
This keeps each adapter a pure, independently-testable unit: given a sample
native-output string, `parse()` returns Findings, no Docker or network needed.

Adapters register themselves in the REGISTRY via `register()`.
"""
from __future__ import annotations

from typing import Dict, List, Type

from ..schema import Finding, STATIC, DYNAMIC  # noqa: F401 (re-exported for adapters)


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


# ---- registry ----------------------------------------------------------------
REGISTRY: Dict[str, BaseAdapter] = {}


def register(cls: Type[BaseAdapter]) -> Type[BaseAdapter]:
    """Class decorator: instantiate + register an adapter under its NAME."""
    if not cls.NAME:
        raise ValueError(f"{cls.__name__} must set NAME")
    REGISTRY[cls.NAME] = cls()
    return cls


def get(name: str) -> BaseAdapter:
    return REGISTRY[name]


def for_pipeline(pipeline: str) -> List[BaseAdapter]:
    return [a for a in REGISTRY.values() if a.PIPELINE == pipeline]
