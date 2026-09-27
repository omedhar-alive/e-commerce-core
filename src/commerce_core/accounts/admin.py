"""User administration. Deactivation and password changes go through the
services, so ``token_version`` is bumped on every path (A4b)."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm

from commerce_core.accounts import services
from commerce_core.accounts.models import User


class PasswordChangeForm(AdminPasswordChangeForm):
    def save(self, commit=True):
        services.change_password(self.user, self.cleaned_data["password1"])
        return self.user


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active", "groups")
    search_fields = ("email", "first_name", "last_name")
    readonly_fields = ("token_version", "last_login", "date_joined")
    show_full_result_count = False
    change_password_form = PasswordChangeForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal",
            {"fields": ("first_name", "last_name", "phone", "country", "preferred_language")},
        ),
        (
            "Access",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Record", {"fields": ("token_version", "last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    def save_model(self, request, obj, form, change):
        deactivating = change and "is_active" in form.changed_data and not obj.is_active
        super().save_model(request, obj, form, change)
        if deactivating:
            services.bump_token_version(obj)
