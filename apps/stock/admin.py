from django.contrib import admin

from .models import MouvementStock, UniteStock


@admin.register(UniteStock)
class UniteStockAdmin(admin.ModelAdmin):
    list_display = ("numero_serie", "type_article", "fournisseur", "statut", "sortie", "reception", "date_entree")
    list_filter = ("type_article", "statut", "fournisseur")
    search_fields = ("numero_serie", "code_interne", "reference_lot")
    autocomplete_fields = ("fournisseur", "sortie", "reception")
    date_hierarchy = "date_entree"
    ordering = ("-date_entree",)


@admin.register(MouvementStock)
class MouvementStockAdmin(admin.ModelAdmin):
    """Journal d'audit du stock — consultation seule, jamais modifiable depuis l'admin."""

    list_display = ("date_mouvement", "type_mouvement", "unite_stock", "sortie", "reception", "utilisateur")
    list_filter = ("type_mouvement",)
    search_fields = ("unite_stock__numero_serie", "commentaire")
    autocomplete_fields = ("unite_stock", "sortie", "reception", "utilisateur")
    date_hierarchy = "date_mouvement"
    ordering = ("-date_mouvement",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
