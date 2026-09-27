"""Settings for CI steps that need Django but no database (makemigrations --check, sqlmigrate)."""

from commerce_core.platform.conf.django_settings import build

globals().update(
    build(
        role=None,
        env={
            "DEPLOYMENT_ENV": "test",
            "SECRET_KEY": "ci-only-" + "x" * 50,
            "STORE_CURRENCY": "EGP",
            "STORE_TIMEZONE": "UTC",
            "ALERT_RECIPIENTS": "ci@example.test",
            "EMAIL_FROM": "ci@example.test",
            "SMTP_HOST": "localhost",
        },
    )
)
