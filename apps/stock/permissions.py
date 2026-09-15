"""
=============================================================================
 apps/stock/permissions.py
 Lecture seule pour l'instant : IsAuthenticated suffit, aucune règle de
 rôle à appliquer tant qu'il n'y a pas d'écriture directe sur ce endpoint
 (elle arrivera via apps/sorties/ et apps/receptions/, Jalon 2+).
=============================================================================
"""

from rest_framework.permissions import IsAuthenticated

__all__ = ["IsAuthenticated"]
