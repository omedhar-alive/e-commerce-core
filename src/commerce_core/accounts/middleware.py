"""Admin sessions end after ADMIN_SESSION_IDLE_TIMEOUT without activity (A6b)."""

import time

from django.contrib.auth import logout

from commerce_core.platform.conf import get_setting

SESSION_KEY = "_last_activity"


class AdminIdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            now = time.time()
            last = request.session.get(SESSION_KEY)
            limit = get_setting("ADMIN_SESSION_IDLE_TIMEOUT").total_seconds()
            if last is not None and now - last > limit:
                logout(request)
            else:
                request.session[SESSION_KEY] = now
        return self.get_response(request)
