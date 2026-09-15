"""
=============================================================================
 apps/notifications/serializers.py
=============================================================================
"""

from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "type", "titre", "corps", "lien", "lu", "lu_le", "created_at"]
        read_only_fields = fields


class ClesPushSerializer(serializers.Serializer):
    p256dh = serializers.CharField()
    auth = serializers.CharField()


class AbonnementPushSerializer(serializers.Serializer):
    """Reçoit la forme renvoyée par `PushSubscription.toJSON()` côté navigateur."""

    endpoint = serializers.CharField()
    keys = ClesPushSerializer()
    user_agent = serializers.CharField(required=False, allow_blank=True, default="")


class DesabonnementSerializer(serializers.Serializer):
    endpoint = serializers.CharField()
