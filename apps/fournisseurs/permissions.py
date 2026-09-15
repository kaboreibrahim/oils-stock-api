"""
=============================================================================
 apps/fournisseurs/permissions.py
 Lecture pour tous ; écriture réservée à l'administrateur (§09 du dossier
 de conception). Logique partagée avec d'autres apps -> apps/common/permissions.py.
=============================================================================
"""

from apps.common.permissions import IsAdminOrReadOnly

__all__ = ["IsAdminOrReadOnly"]
