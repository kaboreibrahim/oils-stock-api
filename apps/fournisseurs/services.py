"""
=============================================================================
 apps/fournisseurs/services.py
 Règles métier des fournisseurs. Aucun accès direct à l'ORM ici : tout passe
 par FournisseurRepository.
=============================================================================
"""

import logging

from django.core.exceptions import ValidationError

from apps.common.services import HistoriqueActionService

from .models import Fournisseur
from .repositories import FournisseurRepository

logger = logging.getLogger("apps.fournisseurs")


class FournisseurService:
    def __init__(
        self,
        repo: FournisseurRepository | None = None,
        historique: HistoriqueActionService | None = None,
    ):
        self.repo = repo or FournisseurRepository()
        self.historique = historique or HistoriqueActionService()

    def lister(self):
        return self.repo.get_all()

    def obtenir(self, fournisseur_id) -> Fournisseur:
        fournisseur = self.repo.get_by_id(fournisseur_id)
        if fournisseur is None:
            raise Fournisseur.DoesNotExist("Fournisseur introuvable.")
        return fournisseur

    def creer(self, donnees: dict, utilisateur) -> Fournisseur:
        donnees = dict(donnees)
        donnees["code"] = self._normaliser_code(donnees.get("code"))
        if self.repo.get_by_code(donnees["code"]):
            raise ValidationError(f"Le code fournisseur « {donnees['code']} » existe déjà.")

        fournisseur = self.repo.create(**donnees)
        self.historique.enregistrer(
            utilisateur=utilisateur, action="CREATION", app="fournisseurs",
            objet_type="Fournisseur", objet_id=fournisseur.id,
            resume=f"Création du fournisseur {fournisseur.code}",
        )
        logger.info("Fournisseur créé : %s", fournisseur.code)
        return fournisseur

    def modifier(self, fournisseur: Fournisseur, donnees: dict, utilisateur) -> Fournisseur:
        donnees = dict(donnees)
        if donnees.get("code"):
            donnees["code"] = self._normaliser_code(donnees["code"])
            existant = self.repo.get_by_code(donnees["code"])
            if existant and existant.pk != fournisseur.pk:
                raise ValidationError(f"Le code fournisseur « {donnees['code']} » existe déjà.")

        fournisseur = self.repo.update(fournisseur, **donnees)
        self.historique.enregistrer(
            utilisateur=utilisateur, action="MODIFICATION", app="fournisseurs",
            objet_type="Fournisseur", objet_id=fournisseur.id,
            resume=f"Modification du fournisseur {fournisseur.code}",
        )
        return fournisseur

    def supprimer(self, fournisseur: Fournisseur, utilisateur) -> None:
        code = fournisseur.code
        self.repo.delete(fournisseur)
        self.historique.enregistrer(
            utilisateur=utilisateur, action="SUPPRESSION", app="fournisseurs",
            objet_type="Fournisseur", objet_id=fournisseur.id,
            resume=f"Suppression du fournisseur {code}",
        )

    @staticmethod
    def _normaliser_code(code) -> str:
        if not code:
            raise ValidationError("Le code fournisseur est obligatoire.")
        return code.strip().upper()
