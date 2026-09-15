"""
=============================================================================
 apps/sorties/permissions.py
 Lecture pour tous ; écriture (créer/modifier/supprimer/ajouter-retirer une
 ligne/valider) pour magasinier et administrateur (§09 du dossier de
 conception). Annuler une sortie déjà validée est réservé à l'ADMIN seul
 (Jalon 6 — §09, note *, tranchée : opération sensible sur un document déjà
 répercuté sur le stock réel) — voir SortieViewSet.get_permissions().
=============================================================================
"""

from apps.common.permissions import IsAdmin, IsMagasinierOrReadOnly

__all__ = ["IsAdmin", "IsMagasinierOrReadOnly"]
