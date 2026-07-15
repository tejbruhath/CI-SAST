"""Adapter registry. Importing this package registers every tool adapter.

Adding a scanner = drop a module here that `@register`s a BaseAdapter subclass,
then import it below. Nothing else in the system needs to change.
"""
from .base import BaseAdapter, REGISTRY, register, get, for_pipeline  # noqa: F401  # re-export registry API

# Import order = deterministic dispatch order (cheapest/fastest first).
from . import gitleaks   # noqa: F401,E402  static: secrets  # side-effect: @register
from . import semgrep    # noqa: F401,E402  static: SAST  # side-effect: @register
from . import trivy      # noqa: F401,E402  static: SCA/CVE  # side-effect: @register
from . import zap        # noqa: F401,E402  dynamic: DAST baseline  # side-effect: @register
from . import nuclei     # noqa: F401,E402  dynamic: template CVE/misconfig  # side-effect: @register

__all__ = ["BaseAdapter", "REGISTRY", "register", "get", "for_pipeline"]  # public package surface
