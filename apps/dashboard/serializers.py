"""
=============================================================================
 apps/dashboard/serializers.py
 Sérialiseurs simples (serializers.Serializer, pas de ModelSerializer) — les
 quatre rapports sont calculés par DashboardService, pas lus tels quels
 depuis un modèle.
=============================================================================
"""

from rest_framework import serializers


class FournisseurLiteSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    nom = serializers.CharField()


class StockDormantSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    numero_serie = serializers.CharField()
    code_interne = serializers.CharField(allow_null=True)
    type_article = serializers.CharField()
    fournisseur = FournisseurLiteSerializer()
    date_reference = serializers.DateField()
    source_date = serializers.ChoiceField(choices=["DERNIERE_SORTIE", "ENTREE"])
    jours_ecoules = serializers.IntegerField()
    # None si le fournisseur n'a pas de coût unitaire configuré pour ce type —
    # jamais une valeur inventée, voir DashboardService.lister_stock_dormant.
    valeur_immobilisee = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)


class SeuilReapproSerializer(serializers.Serializer):
    fournisseur = FournisseurLiteSerializer()
    type_article = serializers.CharField()
    stock_actuel = serializers.IntegerField()
    seuil = serializers.IntegerField(allow_null=True)
    source_seuil = serializers.ChoiceField(choices=["MANUEL", "CALCULE"], allow_null=True)
    en_alerte = serializers.BooleanField()


class SortiesMensuellesSerializer(serializers.Serializer):
    mois = serializers.ListField(child=serializers.CharField())
    flexitank = serializers.ListField(child=serializers.IntegerField())
    heating_pad = serializers.ListField(child=serializers.IntegerField())
    flexitank_moyenne_mobile = serializers.ListField(child=serializers.FloatField(allow_null=True))
    heating_pad_moyenne_mobile = serializers.ListField(child=serializers.FloatField(allow_null=True))


class PrevisionSerializer(serializers.Serializer):
    fournisseur = FournisseurLiteSerializer()
    type_article = serializers.CharField()
    stock_actuel = serializers.IntegerField()
    consommation_moyenne_journaliere = serializers.FloatField()
    seuil = serializers.IntegerField(allow_null=True)
    source_seuil = serializers.ChoiceField(choices=["MANUEL", "CALCULE"], allow_null=True)
    jours_avant_rupture = serializers.FloatField(allow_null=True)
    date_commande_recommandee = serializers.DateField(allow_null=True)
    en_alerte = serializers.BooleanField()
