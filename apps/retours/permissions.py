"""
=============================================================================
 apps/retours/permissions.py
 Enregistrer un retour est réservé à magasinier et administrateur (§09 du
 dossier de conception) — pas de lecture ici, l'action n'a pas d'équivalent
 GET (l'historique des retours se lit via /api/v1/mouvements/?type_mouvement=RETOUR).
=============================================================================
"""

from apps.common.permissions import IsMagasinierOrReadOnly

__all__ = ["IsMagasinierOrReadOnly"]
