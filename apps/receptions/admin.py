from django.contrib import admin

from .models import LigneReception, Reception


class LigneReceptionInline(admin.TabularInline):
    model = LigneReception
    extra = 0
    autocomplete_fields = ("fournisseur",)
    readonly_fields = ("ajoute_le",)


@admin.register(Reception)
class ReceptionAdmin(admin.ModelAdmin):
    list_display = ("reference", "nature", "fournisseur", "fichier", "date_reception", "statut")
    list_filter = ("nature", "statut")
    search_fields = ("reference", "reference_fournisseur", "fournisseur__nom", "fournisseur__code")
    autocomplete_fields = ("fournisseur",)
    date_hierarchy = "date_reception"
    ordering = ("-date_reception",)
    inlines = [LigneReceptionInline]
