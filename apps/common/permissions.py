"""
=============================================================================
 apps/common/permissions.py
 Permissions DRF génériques par rôle (§09 du dossier de conception). Chaque
 app métier importe/réexporte celles qui la concernent dans son propre
 permissions.py plutôt que de dupliquer la logique.
=============================================================================
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAdmin(BasePermission):
    """Réservé aux administrateurs (ex. gestion des utilisateurs)."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.est_admin)


class IsAdminOrReadOnly(BasePermission):
    """Lecture pour tout utilisateur authentifié, écriture réservée à l'administrateur."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.est_admin


class IsMagasinierOrReadOnly(BasePermission):
    """Lecture pour tout utilisateur authentifié, écriture pour magasinier et administrateur."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.peut_ecrire
