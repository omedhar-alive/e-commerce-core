"""Platform admin: runtime settings change only through the audited service (F1c)."""

from django import forms
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from commerce_core.accounts import permissions
from commerce_core.platform.admin_base import ReadOnlyModelAdmin
from commerce_core.platform.errors.exceptions import DomainError
from commerce_core.platform.models import RuntimeSetting, SettingChange
from commerce_core.platform.runtime_settings.services import change_runtime_setting


class ChangeSettingForm(forms.Form):
    enabled = forms.BooleanField(required=False)
    reason = forms.CharField(widget=forms.Textarea, max_length=2000)


@admin.register(RuntimeSetting)
class RuntimeSettingAdmin(ReadOnlyModelAdmin):
    list_display = ("kind", "provider_key", "enabled", "updated_at")
    actions = ["change_setting"]

    def has_manage_settings_permission(self, request):
        return request.user.has_perm(permissions.full_name(permissions.MANAGE_SETTINGS))

    @admin.action(description="Change setting", permissions=["manage_settings"])
    def change_setting(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one setting.", messages.ERROR)
            return None
        return redirect(
            reverse("admin:platform_runtimesetting_change_setting", args=[queryset.get().pk])
        )

    def get_urls(self):
        return [
            path(
                "<int:pk>/change-setting/",
                self.admin_site.admin_view(self.change_setting_view),
                name="platform_runtimesetting_change_setting",
            ),
            *super().get_urls(),
        ]

    def change_setting_view(self, request, pk):
        setting = get_object_or_404(RuntimeSetting, pk=pk)
        form = ChangeSettingForm(request.POST or None, initial={"enabled": setting.enabled})
        if request.method == "POST" and form.is_valid():
            try:
                change_runtime_setting(
                    request.user,
                    kind=setting.kind,
                    provider_key=setting.provider_key,
                    enabled=form.cleaned_data["enabled"],
                    reason=form.cleaned_data["reason"],
                )
            except DomainError as exc:
                self.message_user(request, str(exc.spec().message), messages.ERROR)
            else:
                self.message_user(request, "Setting changed.", messages.SUCCESS)
                return redirect("admin:platform_runtimesetting_changelist")
        context = {**self.admin_site.each_context(request), "setting": setting, "form": form}
        return TemplateResponse(
            request, "admin/platform/runtimesetting/change_setting.html", context
        )


@admin.register(SettingChange)
class SettingChangeAdmin(ReadOnlyModelAdmin):
    list_display = (
        "created_at",
        "kind",
        "provider_key",
        "before",
        "after",
        "actor_type",
        "actor_id",
    )
    list_filter = ("kind",)
    date_hierarchy = "created_at"
