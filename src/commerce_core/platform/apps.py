from django.apps import AppConfig


class PlatformConfig(AppConfig):
    name = "commerce_core.platform"
    label = "platform"
    verbose_name = "Platform"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from commerce_core.platform import checks  # noqa: F401  (registers system checks)
        from commerce_core.platform.jobs import builtin  # noqa: F401  (registers jobs)
