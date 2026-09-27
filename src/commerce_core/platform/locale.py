"""Language resolution (L3, L3a).

First match wins:
1. the order's language, for anything about an order (O8);
2. the user's ``preferred_language``;
3. ``Accept-Language``, limited to installed languages;
4. ``STORE_DEFAULT_LANGUAGE``.
"""

from django.utils import translation

from commerce_core.platform.conf import get_setting
from commerce_core.platform.conf.registry import SUPPORTED_LANGUAGES


def installed_languages() -> tuple[str, ...]:
    return tuple(get_setting("INSTALLED_LANGUAGES"))


def text_direction(language: str) -> str:
    return SUPPORTED_LANGUAGES[language]


def _accept_language(header: str, installed: tuple[str, ...]) -> str | None:
    choices = []
    for position, part in enumerate(header.split(",")):
        tag, _, params = part.strip().partition(";")
        tag = tag.strip().lower()
        if not tag or tag == "*":
            continue
        q = 1.0
        for param in params.split(";"):
            name, _, value = param.strip().partition("=")
            if name == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if q > 0:
            choices.append((-q, position, tag))
    for _, _, tag in sorted(choices):
        for candidate in (tag, tag.split("-")[0]):
            if candidate in installed:
                return candidate
    return None


def resolve_language(request=None, user=None, order=None) -> str:
    installed = installed_languages()
    order_language = getattr(order, "language", None)
    if order_language in installed:
        return order_language
    preferred = getattr(user, "preferred_language", None) if user is not None else None
    if preferred in installed:
        return preferred
    if request is not None:
        found = _accept_language(request.headers.get("Accept-Language", ""), installed)
        if found:
            return found
    return get_setting("STORE_DEFAULT_LANGUAGE")


class LanguageMiddleware:
    """Activates the L3a language for the request; error messages render in it (X7)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        language = resolve_language(
            request, user if user is not None and user.is_authenticated else None
        )
        with translation.override(language):
            request.LANGUAGE_CODE = language
            response = self.get_response(request)
        response.setdefault("Content-Language", language)
        return response
