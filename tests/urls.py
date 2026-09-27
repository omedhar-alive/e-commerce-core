from django.urls import path

from commerce_core.urls import handler400, handler403, handler404, handler500  # noqa: F401
from commerce_core.urls import urlpatterns as core_urlpatterns
from tests.testapp.api import test_api

urlpatterns = [*core_urlpatterns, path("test-api/", test_api.urls)]
