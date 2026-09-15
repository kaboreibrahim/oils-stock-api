"""
=============================================================================
 apps/clients/services.py
 Règles métier des clients. Aucun accès direct à l'ORM ici : tout passe par
 ClientRepository.
=============================================================================
"""

import logging

from django.core.exceptions import ValidationError

from apps.common.services import HistoriqueActionService

from .models import Client
from .repositories import ClientRepository

logger = logging.getLogger("apps.clients")


class ClientService:
    def __init__(
        self,
        repo: ClientRepository | None = None,
        historique: HistoriqueActionService | None = None,
    ):
        self.repo = repo or ClientRepository()
        self.historique = historique or HistoriqueActionService()

    def lister(self):
        return self.repo.get_all()

    def obtenir(self, client_id) -> Client:
        client = self.repo.get_by_id(client_id)
        if client is None:
            raise Client.DoesNotExist("Client introuvable.")
        return client

    def creer(self, donnees: dict, utilisateur) -> Client:
        donnees = dict(donnees)
        donnees["code"] = self._normaliser_code(donnees.get("code"))
        if self.repo.get_by_code(donnees["code"]):
            raise ValidationError(f"Le code client « {donnees['code']} » existe déjà.")

        client = self.repo.create(**donnees)
        self.historique.enregistrer(
            utilisateur=utilisateur, action="CREATION", app="clients",
            objet_type="Client", objet_id=client.id,
            resume=f"Création du client {client.code}",
        )
        logger.info("Client créé : %s", client.code)
        return client

    def modifier(self, client: Client, donnees: dict, utilisateur) -> Client:
        donnees = dict(donnees)
        if donnees.get("code"):
            donnees["code"] = self._normaliser_code(donnees["code"])
            existant = self.repo.get_by_code(donnees["code"])
            if existant and existant.pk != client.pk:
                raise ValidationError(f"Le code client « {donnees['code']} » existe déjà.")

        client = self.repo.update(client, **donnees)
        self.historique.enregistrer(
            utilisateur=utilisateur, action="MODIFICATION", app="clients",
            objet_type="Client", objet_id=client.id,
            resume=f"Modification du client {client.code}",
        )
        return client

    def supprimer(self, client: Client, utilisateur) -> None:
        code = client.code
        self.repo.delete(client)
        self.historique.enregistrer(
            utilisateur=utilisateur, action="SUPPRESSION", app="clients",
            objet_type="Client", objet_id=client.id,
            resume=f"Suppression du client {code}",
        )

    @staticmethod
    def _normaliser_code(code) -> str:
        if not code:
            raise ValidationError("Le code client est obligatoire.")
        return code.strip().upper()
