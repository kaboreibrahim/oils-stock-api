from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import PasswordResetCode, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (("Rôle applicatif", {"fields": ("role",)}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Rôle applicatif", {"fields": ("role",)}),
    )


@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    """Consultation seule — jamais le code en clair, juste son état."""

    list_display = ("utilisateur", "created_at", "date_expiration", "tentatives", "utilise_le")
    list_filter = ("utilise_le",)
    search_fields = ("utilisateur__username", "utilisateur__email")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
