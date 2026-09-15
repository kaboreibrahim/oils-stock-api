from django.contrib import admin

from .models import HistoriqueAction, IdempotencyRecord


@admin.register(HistoriqueAction)
class HistoriqueActionAdmin(admin.ModelAdmin):
    """Journal d'audit — consultation seule, jamais modifiable depuis l'admin."""

    list_display = ("date", "action", "app", "objet_type", "objet_id", "utilisateur", "resume")
    list_filter = ("action", "app", "objet_type")
    search_fields = ("objet_id", "resume")
    date_hierarchy = "date"
    ordering = ("-date",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    """Clés d'idempotence (écriture hors-ligne) — consultation seule."""

    list_display = ("date_creation", "utilisateur", "methode", "chemin", "statut_code")
    list_filter = ("methode", "statut_code")
    search_fields = ("cle", "chemin")
    date_hierarchy = "date_creation"
    ordering = ("-date_creation",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
