"""L3, L3a, X7: language resolves in L3a order; error messages follow it, codes do not."""

from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from commerce_core.platform.locale import resolve_language, text_direction

pytestmark = pytest.mark.django_db


def _request(accept=None):
    headers = {"HTTP_ACCEPT_LANGUAGE": accept} if accept else {}
    return RequestFactory().get("/", **headers)


def test_order_language_wins():
    user = SimpleNamespace(preferred_language="en")
    assert resolve_language(_request("en"), user, SimpleNamespace(language="ar")) == "ar"


def test_user_preference_beats_accept_language():
    assert resolve_language(_request("en"), SimpleNamespace(preferred_language="ar")) == "ar"


def test_accept_language_limited_to_installed_with_q_values():
    assert resolve_language(_request("fr;q=1, ar-EG;q=0.8, en;q=0.5")) == "ar"
    assert resolve_language(_request("fr, de")) == "en"


def test_falls_back_to_store_default(override_setting):
    override_setting("STORE_DEFAULT_LANGUAGE", "ar")
    assert resolve_language(_request()) == "ar"


def test_uninstalled_preferences_are_skipped(override_setting):
    override_setting("INSTALLED_LANGUAGES", ("en",))
    user, order = SimpleNamespace(preferred_language="ar"), SimpleNamespace(language="ar")
    assert resolve_language(_request("ar"), user, order) == "en"


def test_each_language_has_a_direction():
    assert text_direction("ar") == "rtl" and text_direction("en") == "ltr"


def test_error_message_renders_in_request_language_and_code_does_not_change(client):
    english = client.get("/test-api/missing", HTTP_ACCEPT_LANGUAGE="en").json()["error"]
    arabic = client.get("/test-api/missing", HTTP_ACCEPT_LANGUAGE="ar").json()["error"]
    assert english["code"] == arabic["code"] == "not_found"
    assert english["message"] == "Not found."
    assert arabic["message"] == "غير موجود."


def test_every_error_message_has_an_arabic_translation():
    from django.utils import translation

    from commerce_core.platform.errors.registry import ERRORS

    for spec in ERRORS.values():
        with translation.override("en"):
            english = str(spec.message)
        with translation.override("ar"):
            assert str(spec.message) != english, spec.code
