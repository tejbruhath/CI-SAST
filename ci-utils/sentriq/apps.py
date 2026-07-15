from django.apps import AppConfig  # Django app registration base class


class SentriqConfig(AppConfig):
    """Registers the sentriq Django app (models, signals, admin hooks)."""
    default_auto_field = "django.db.models.BigAutoField"  # default PK type for new models
    name = "sentriq"  # Python package path Django imports for this app
