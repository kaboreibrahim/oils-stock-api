"""
=============================================================================
 apps/notifications/permissions.py
 Chaque utilisateur ne voit / ne modifie que SES propres notifications et
 abonnements (le scoping est fait dans le service via request.user) —
 IsAuthenticated suffit, aucune règle de rôle.
=============================================================================
"""

from rest_framework.permissions import IsAuthenticated

__all__ = ["IsAuthenticated"]
