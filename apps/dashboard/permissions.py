"""
=============================================================================
 apps/dashboard/permissions.py
 Lecture seule, ouverte à tous les rôles authentifiés (même convention que
 fournisseurs/clients/unites/mouvements) — aucune règle de rôle à appliquer,
 ce sont des rapports calculés, pas des ressources à modifier.
=============================================================================
"""

from rest_framework.permissions import IsAuthenticated

__all__ = ["IsAuthenticated"]
