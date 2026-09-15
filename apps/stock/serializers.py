from rest_framework import serializers

from .models import MouvementStock, UniteStock


class UniteStockSerializer(serializers.ModelSerializer):
    fournisseur_code = serializers.CharField(source="fournisseur.code", read_only=True)
    reception_reference = serializers.CharField(source="reception.reference", read_only=True, default=None)

    class Meta:
        model = UniteStock
        fields = [
            "id", "numero_serie", "code_interne", "type_article", "fournisseur",
            "fournisseur_code", "statut", "sortie", "reception", "reception_reference",
            "date_entree", "date_sortie", "emplacement", "reference_lot", "attributs",
            "created_at", "updated_at",
        ]
        # Aucune écriture ici : les unités naissent via la validation d'une
        # Reception (apps.receptions) ; `statut`/`sortie` changent via
        # apps.sorties et apps.retours (valider/annuler une sortie, retour).
        read_only_fields = fields


class CandidatScanSerializer(serializers.Serializer):
    """Un jeton détecté par OCR sur une photo de scan mobile (Jalon 5), avec
    les unités qu'il résout — liste vide si aucune correspondance."""

    candidat = serializers.CharField()
    unites = UniteStockSerializer(many=True)


class MouvementStockSerializer(serializers.ModelSerializer):
    numero_serie = serializers.CharField(source="unite_stock.numero_serie", read_only=True)
    sortie_reference = serializers.CharField(source="sortie.reference", read_only=True, default=None)
    reception_reference = serializers.CharField(source="reception.reference", read_only=True, default=None)
    utilisateur_username = serializers.CharField(source="utilisateur.username", read_only=True, default=None)

    class Meta:
        model = MouvementStock
        fields = [
            "id", "unite_stock", "numero_serie", "type_mouvement", "date_mouvement",
            "sortie", "sortie_reference", "reception", "reception_reference",
            "utilisateur", "utilisateur_username", "commentaire", "created_at",
        ]
        read_only_fields = fields
