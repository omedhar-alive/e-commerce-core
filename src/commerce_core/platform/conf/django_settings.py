"""Builds a deployment's Django settings from the registry.

A deployment's ``settings.py`` is one line::

    globals().update(build())

``build()`` validates every setting for this process's role (F1a) and
returns the Django settings. It is the only place that reads the process
environment. Validation therefore runs in every process at boot: web, worker,
scheduler and the release step, not only under ``manage.py check``.
"""

import os
from collections.abc import Mapping
from typing import Any

from commerce_core.platform import conf
from commerce_core.platform.conf import boot
from commerce_core.platform.conf.process import detect_role
from commerce_core.platform.conf.registry import SUPPORTED_LANGUAGES, DeploymentEnv, Role

_ROLE_URL = {
    Role.WEB: "WEB_DATABASE_URL",
    Role.JOB: "JOB_DATABASE_URL",
    Role.MIGRATION: "MIGRATION_DATABASE_URL",
}

CORE_APPS = [
    "commerce_core.accounts.apps.CoreAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_tasks",
    "django_tasks_db",
    "commerce_core.accounts",
    "commerce_core.platform",
]


def build(role: Role | None = ..., env: Mapping[str, str] | None = None) -> dict[str, Any]:
    if role is ...:
        role = detect_role()
    values = boot.load(role, os.environ if env is None else env)
    conf.install(values)
    production = values["DEPLOYMENT_ENV"] == DeploymentEnv.PRODUCTION

    databases = {}
    if role is not None:
        databases["default"] = values[_ROLE_URL[role]]

    return {
        "SECRET_KEY": values["SECRET_KEY"],
        "DEBUG": values["DEBUG"],
        "ALLOWED_HOSTS": list(values.get("ALLOWED_HOSTS", ())),
        "INSTALLED_APPS": list(CORE_APPS),
        "DATABASES": databases,
        "DEFAULT_AUTO_FIELD": "django.db.models.BigAutoField",
        "ROOT_URLCONF": "commerce_core.urls",
        # A1, A1a, A1b
        "AUTH_USER_MODEL": "accounts.User",
        "AUTHENTICATION_BACKENDS": ["commerce_core.accounts.backends.EmailBackend"],
        "SILENCED_SYSTEM_CHECKS": ["auth.W004"],
        "PASSWORD_HASHERS": [
            "django.contrib.auth.hashers.Argon2PasswordHasher",
            "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        ],
        "AUTH_PASSWORD_VALIDATORS": [
            {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
            {
                "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
                "OPTIONS": {"min_length": 12},
            },
            {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
            {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
        ],
        # L1, L2, L3
        "USE_TZ": True,
        "TIME_ZONE": "UTC",
        "USE_I18N": True,
        "LANGUAGE_CODE": values["STORE_DEFAULT_LANGUAGE"],
        "LANGUAGES": [(code, code) for code in values["INSTALLED_LANGUAGES"]],
        "LANGUAGES_BIDI": [c for c, d in SUPPORTED_LANGUAGES.items() if d == "rtl"],
        # Background tasks (django.tasks API on the django-tasks backport)
        "TASKS": {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}},
        # Admin sessions (A2, A5, A6b)
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": production,
        "SESSION_COOKIE_SAMESITE": "Strict",
        "SESSION_COOKIE_AGE": 12 * 3600,
        "CSRF_COOKIE_SECURE": production,
        "CSRF_COOKIE_HTTPONLY": True,
        "CSRF_COOKIE_SAMESITE": "Strict",
        "CSRF_FAILURE_VIEW": "commerce_core.platform.errors.handlers.csrf_failure",
        "LOGIN_URL": "admin:login",
        "X_FRAME_OPTIONS": "DENY",
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "SECURE_REFERRER_POLICY": "same-origin",
        "SECURE_SSL_REDIRECT": production,
        "SECURE_HSTS_SECONDS": 31536000 if production else 0,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": production,
        "SECURE_PROXY_SSL_HEADER": (
            ("HTTP_X_FORWARDED_PROTO", "https") if values["TRUSTED_PROXY_HOPS"] else None
        ),
        "MIDDLEWARE": [
            "commerce_core.platform.api.middleware.RequestIdMiddleware",
            "commerce_core.platform.api.middleware.BodyCapMiddleware",
            "commerce_core.platform.errors.handlers.DatabaseTimeoutMiddleware",
            "django.middleware.security.SecurityMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.common.CommonMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django_otp.middleware.OTPMiddleware",
            "commerce_core.accounts.middleware.AdminIdleTimeoutMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
            "django.middleware.clickjacking.XFrameOptionsMiddleware",
        ],
        "TEMPLATES": [
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ]
                },
            }
        ],
        "DATA_UPLOAD_MAX_MEMORY_SIZE": 1024 * 1024,
        "STATIC_URL": "static/",
        "STATIC_ROOT": "staticfiles",
    }
