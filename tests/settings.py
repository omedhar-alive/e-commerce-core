"""Test settings. Tests connect as the web role (phase plan, section 4).

The harness in ``tests/harness.py`` builds the database as the migration role
and switches the connection to web before any test runs.
"""

import os

SECRET_KEY = "test-only-not-secret"
USE_TZ = True
TIME_ZONE = "UTC"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "commerce_core.platform",
]

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
