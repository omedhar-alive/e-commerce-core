from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "commerce_core.accounts"
    label = "accounts"
    verbose_name = "Accounts"
    default_auto_field = "django.db.models.BigAutoField"
