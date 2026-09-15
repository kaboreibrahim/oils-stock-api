from django.contrib import admin

from .models import Fournisseur


@admin.register(Fournisseur)
class FournisseurAdmin(admin.ModelAdmin):
    list_display = ("code", "nom", "pays", "actif", "mode_extraction")
    list_filter = ("actif", "pays", "mode_extraction")
    search_fields = ("code", "nom")
    ordering = ("nom",)
    fieldsets = (
        (None, {"fields": ("code", "nom", "pays", "actif", "notes")}),
        ("Contact", {"fields": ("contact_nom", "contact_email", "contact_tel")}),
        (
            "Profil d'extraction (Jalon 4)",
            {"fields": ("mode_extraction", "regex_numero_serie", "type_article_defaut")},
        ),
    )
