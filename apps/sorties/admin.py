from django.contrib import admin

from .models import LigneSortie, Sortie


class LigneSortieInline(admin.TabularInline):
    model = LigneSortie
    extra = 0
    autocomplete_fields = ("unite_stock",)
    readonly_fields = ("ajoute_le",)


@admin.register(Sortie)
class SortieAdmin(admin.ModelAdmin):
    list_display = ("reference", "client", "projet", "trd", "date_sortie", "statut")
    list_filter = ("statut",)
    search_fields = ("reference", "client__nom", "projet", "trd")
    autocomplete_fields = ("client",)
    date_hierarchy = "date_sortie"
    ordering = ("-date_sortie",)
    inlines = [LigneSortieInline]
