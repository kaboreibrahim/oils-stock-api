"""
=============================================================================
 apps/receptions/permissions.py
 Lecture pour tous ; écriture (créer/modifier/supprimer/ajouter-retirer une
 ligne/valider) pour magasinier et administrateur (§09 du dossier de
 conception). La restriction supplémentaire « reprise réservée à l'admin »
 dépend du contenu de la requête (`nature`) : appliquée dans
 ReceptionService.creer, pas ici (django.core.exceptions.PermissionDenied,
 traduite en 403 par DRF). Annuler une réception déjà validée est réservé à
 l'ADMIN seul (Jalon 6 — §09, note *, tranchée) — voir
 ReceptionViewSet.get_permissions().
=============================================================================
"""

from apps.common.permissions import IsAdmin, IsMagasinierOrReadOnly

__all__ = ["IsAdmin", "IsMagasinierOrReadOnly"]
