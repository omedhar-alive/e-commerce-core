"""Core URLs. A deployment serves these and adds nothing domain-specific (W2)."""

from django.contrib import admin
from django.urls import path

from commerce_core.platform.api.core import api
from commerce_core.platform.health import views as health

urlpatterns = [
    path("health", health.health, name="health"),
    path("health/jobs", health.health_jobs, name="health-jobs"),
    path("health/detail", health.health_detail, name="health-detail"),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]

handler400 = "commerce_core.platform.errors.handlers.handler400"
handler403 = "commerce_core.platform.errors.handlers.handler403"
handler404 = "commerce_core.platform.errors.handlers.handler404"
handler500 = "commerce_core.platform.errors.handlers.handler500"
