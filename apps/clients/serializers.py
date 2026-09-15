from rest_framework import serializers

from .models import Client


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = [
            "id", "code", "nom", "contact_nom", "contact_email", "contact_tel",
            "adresse", "pays", "actif", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
