from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class AccountsConfig(AppConfig):
    name = "commerce_core.accounts"
    label = "accounts"
    verbose_name = "Accounts"
    default_auto_field = "django.db.models.BigAutoField"


class CoreAdminConfig(admin_apps.AdminConfig):
    """The admin ships inside core (W1b), on an OTP-enforcing site (A6b)."""

    default = False
    default_site = "commerce_core.accounts.admin_site.CoreAdminSite"
