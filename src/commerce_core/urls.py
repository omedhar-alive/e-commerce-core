"""Core URLs. A deployment includes these and adds nothing domain-specific (W2)."""

from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
