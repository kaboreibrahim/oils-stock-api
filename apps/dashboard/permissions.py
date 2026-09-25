"""
=============================================================================
 apps/dashboard/permissions.py
 Lecture seule, ouverte à tous les rôles authentifiés (même convention que
 fournisseurs/clients/unites/mouvements) — aucune règle de rôle à appliquer,
 ce sont des rapports calculés, pas des ressources à modifier. Ouvert aussi à
 la clé de service EmpotaveV2 (voir apps.common.service_auth) pour le
 dashboard "Appro Stock" côté EmpotaveV2.
=============================================================================
"""

from rest_framework.permissions import IsAuthenticated

from apps.common.service_auth import IsEmpotageService

__all__ = ["IsAuthenticated", "IsEmpotageService"]
