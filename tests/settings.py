"""Test settings, built through the same registry as a deployment's.

Tests connect as the web role (phase plan section 4). ``tests/harness.py``
builds the database as the migration role and switches the connection to web
before any test runs.
"""

import os

from commerce_core.platform.conf.django_settings import build

TEST_ENV = {
    "DEPLOYMENT_ENV": "test",
    "SECRET_KEY": "test-only-" + "x" * 50,
    "STORE_CURRENCY": "EGP",
    "STORE_TIMEZONE": "Africa/Cairo",
    "INSTALLED_LANGUAGES": "en,ar",
    "STORE_DEFAULT_LANGUAGE": "en",
    "ALERT_RECIPIENTS": "alerts@example.test",
    "EMAIL_FROM": "store@example.test",
    "SMTP_HOST": "localhost",
    "SMTP_PORT": "2525",
    "SMTP_SECURITY": "none",
    "MONITORING_TOKEN": "t" * 40,
}

globals().update(build(role=None, env=TEST_ENV))

INSTALLED_APPS = INSTALLED_APPS + ["tests.testapp"]  # noqa: F821
ALLOWED_HOSTS = ["testserver"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("COMMERCE_TEST_DB_NAME", "commerce_test"),
        "USER": "commerce_web",
        "PASSWORD": os.environ.get("COMMERCE_TEST_ROLE_PASSWORD", "commerce-test-only"),
        "HOST": os.environ.get("COMMERCE_TEST_DB_HOST", ""),
        "PORT": os.environ.get("COMMERCE_TEST_DB_PORT", ""),
    }
}
