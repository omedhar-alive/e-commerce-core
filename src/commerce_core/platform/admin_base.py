"""Admin base classes for rows that are never edited through a form."""

from django.contrib import admin


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """Visible, never added, changed or deleted through the admin.

    Every D7/D7a-governed model uses this (D7b): a change form saves the
    whole row, which the grants refuse. Changes go through admin actions that
    call the domain services.
    """

    show_full_result_count = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
