from django.apps import AppConfig  # Base class every Django app config must extend.


class OrchestratorConfig(AppConfig):  # Registers this package as the "orchestrator" app.
    name = "orchestrator"  # Python package path Django uses for app discovery.
