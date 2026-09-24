"""
=============================================================================
 apps/common/service_auth.py
 Authentification serveur-à-serveur pour l'intégration EmpotaveV2 : clé API
 (header X-API-Key) + liste blanche d'IP. Pas de JWT, pas de request.user réel
 (AnonymousUser) — cree_par/valide_par restent donc None sur ces appels, déjà
 géré par SortieService. À combiner en OR avec les permissions humaines
 existantes (ex. IsMagasinierOrReadOnly | IsEmpotageService), jamais en
 remplacement, pour que le frontend JWT garde son accès normal.
=============================================================================
"""

import secrets

from django.conf import settings
from rest_framework.permissions import BasePermission


class IsEmpotageService(BasePermission):
    """Autorise un appel si la clé API et l'IP source sont toutes deux valides."""

    def has_permission(self, request, view) -> bool:
        cle_attendue = settings.EMPOTAGE_API_KEY
        cle_recue = request.headers.get("X-API-Key", "")
        if not cle_attendue or not secrets.compare_digest(cle_recue, cle_attendue):
            return False

        ips_autorisees = settings.EMPOTAGE_ALLOWED_IPS
        if not ips_autorisees:
            return False
        return request.META.get("REMOTE_ADDR", "") in ips_autorisees
