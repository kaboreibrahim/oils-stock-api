from django.contrib import admin

from .models import Notification, PushSubscription


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Consultation seule — les notifications sont créées par le service, pas à la main."""

    list_display = ("created_at", "type", "titre", "destinataire", "lu", "lu_le")
    list_filter = ("type", "lu")
    search_fields = ("titre", "corps", "destinataire__username")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "utilisateur", "endpoint", "user_agent")
    search_fields = ("utilisateur__username", "endpoint")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
