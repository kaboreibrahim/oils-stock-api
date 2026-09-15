"""
=============================================================================
 apps/sorties/serializers.py
=============================================================================
"""

from rest_framework import serializers

from .models import LigneSortie, Sortie


class LigneSortieSerializer(serializers.ModelSerializer):
    numero_serie = serializers.CharField(source="unite_stock.numero_serie", read_only=True)
    type_article = serializers.CharField(source="unite_stock.type_article", read_only=True)
    fournisseur_code = serializers.CharField(source="unite_stock.fournisseur.code", read_only=True)

    class Meta:
        model = LigneSortie
        fields = ["id", "unite_stock", "numero_serie", "type_article", "fournisseur_code", "ajoute_le"]
        read_only_fields = fields


class SortieSerializer(serializers.ModelSerializer):
    client_nom = serializers.CharField(source="client.nom", read_only=True)
    # default=0 : une Sortie tout juste créée (via .create(), pas la queryset
    # annotée de get_all()) n'a pas l'attribut nb_unites — sans default, DRF
    # omettrait simplement le champ (SkipField) plutôt que d'afficher 0.
    nb_unites = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Sortie
        fields = [
            "id", "reference", "client", "client_nom", "projet", "trd", "date_sortie",
            "statut", "nb_unites", "valide_le", "annule_le", "motif_annulation", "notes",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "reference", "statut", "nb_unites", "valide_le", "annule_le",
            "motif_annulation", "created_at", "updated_at",
        ]


class SortieDetailSerializer(SortieSerializer):
    lignes = LigneSortieSerializer(many=True, read_only=True)

    class Meta(SortieSerializer.Meta):
        fields = SortieSerializer.Meta.fields + ["lignes"]


class AjouterLigneSerializer(serializers.Serializer):
    """Contrat JSON : `{"numero_serie": "...", "fournisseur": "<uuid>"}` (fournisseur optionnel,
    utile seulement si le numéro de série est partagé par plusieurs fournisseurs)."""

    numero_serie = serializers.CharField(max_length=100)
    fournisseur = serializers.UUIDField(required=False, allow_null=True)


class AnnulerSortieSerializer(serializers.Serializer):
    """Contrat JSON : `{"motif": "..."}`."""

    motif = serializers.CharField(max_length=255)
