"""T4 (A2, A5, A1b, Q3c): a production web build carries the hardened settings."""

import pytest

from commerce_core.platform import conf
from commerce_core.platform.conf.django_settings import build
from commerce_core.platform.conf.registry import Role
from tests.settings import TEST_ENV

PRODUCTION_ENV = {
    **TEST_ENV,
    "DEPLOYMENT_ENV": "production",
    "ERROR_TRACKING_DSN": "https://public@errors.invalid/1",
    "ALLOWED_HOSTS": "api.example.test",
    "WEB_DATABASE_URL": "postgresql://commerce_web:pw@db.invalid:5432/commerce?sslmode=require",
    "TRUSTED_PROXY_HOPS": "1",
}


@pytest.fixture
def production_web(monkeypatch):
    """Build as a production web process without leaving its state behind."""
    initialised = []
    monkeypatch.setattr(
        "commerce_core.platform.sentry.sentry_sdk.init", lambda **kw: initialised.append(kw)
    )
    saved = dict(conf._loaded)
    try:
        yield build(role=Role.WEB, env=PRODUCTION_ENV), initialised
    finally:
        conf.install(saved)


def test_cookies_are_secure(production_web):
    settings, _ = production_web
    assert settings["SESSION_COOKIE_SECURE"] is True
    assert settings["CSRF_COOKIE_SECURE"] is True
    assert settings["SESSION_COOKIE_HTTPONLY"] is True


def test_transport_security(production_web):
    settings, _ = production_web
    assert settings["SECURE_HSTS_SECONDS"] > 0
    assert settings["SECURE_SSL_REDIRECT"] is True
    assert settings["SECURE_PROXY_SSL_HEADER"] == ("HTTP_X_FORWARDED_PROTO", "https")


def test_clickjacking_protection(production_web):
    settings, _ = production_web
    assert settings["X_FRAME_OPTIONS"] == "DENY"
    assert "django.middleware.clickjacking.XFrameOptionsMiddleware" in settings["MIDDLEWARE"]


def test_argon2_is_the_first_hasher(production_web):
    settings, _ = production_web
    assert settings["PASSWORD_HASHERS"][0] == "django.contrib.auth.hashers.Argon2PasswordHasher"


def test_request_body_is_capped_at_one_megabyte(production_web):
    settings, _ = production_web
    assert settings["DATA_UPLOAD_MAX_MEMORY_SIZE"] == 1024 * 1024


def test_web_process_uses_only_the_web_url_and_debug_is_off(production_web):
    settings, _ = production_web
    assert settings["DEBUG"] is False
    assert settings["DATABASES"]["default"]["USER"] == "commerce_web"
    assert settings["DATABASES"]["default"]["OPTIONS"] == {"sslmode": "require"}


def test_error_tracking_is_initialised_with_scrubbing(production_web):
    _, initialised = production_web
    assert len(initialised) == 1
    options = initialised[0]
    assert options["environment"] == "production"
    assert options["send_default_pii"] is False
    assert options["before_send"].__name__ == "before_send"
