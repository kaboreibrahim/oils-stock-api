"""
=============================================================================
 apps/retours/serializers.py
=============================================================================
"""

from rest_framework import serializers


class RetourLigneSerializer(serializers.Serializer):
    numero_serie = serializers.CharField(max_length=100)
    fournisseur = serializers.UUIDField(required=False, allow_null=True)


class RetourSerializer(serializers.Serializer):
    """Contrat JSON :
    `{"unites": [{"numero_serie": "...", "fournisseur": "<uuid>"?}], "date_retour": "AAAA-MM-JJ", "motif": "..."}`.
    """

    unites = RetourLigneSerializer(many=True)
    date_retour = serializers.DateField()
    motif = serializers.CharField(max_length=255)

    def validate_unites(self, value):
        if not value:
            raise serializers.ValidationError("Au moins une unité est requise.")
        return value
