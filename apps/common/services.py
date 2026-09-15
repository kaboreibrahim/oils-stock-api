"""
=============================================================================
 apps/common/services.py
 HistoriqueActionService — point d'entrée unique pour journaliser une action
 métier, quel que soit le domaine appelant. Les services de chaque app
 l'utilisent, ne créent jamais de HistoriqueAction directement.
=============================================================================
"""

import logging

from .repositories import HistoriqueActionRepository

logger = logging.getLogger("apps.common.audit")


class HistoriqueActionService:
    def __init__(self, repo: HistoriqueActionRepository | None = None):
        self.repo = repo or HistoriqueActionRepository()

    def enregistrer(self, *, utilisateur, action, app, objet_type, objet_id, resume="", donnees=None):
        entree = self.repo.creer(
            utilisateur=utilisateur if getattr(utilisateur, "is_authenticated", False) else None,
            action=action,
            app=app,
            objet_type=objet_type,
            objet_id=str(objet_id),
            resume=resume,
            donnees=donnees or {},
        )
        logger.info("audit: %s %s.%s#%s — %s", action, app, objet_type, objet_id, resume)
        return entree
