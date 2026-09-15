"""
=============================================================================
 apps/clients/repositories.py
 Seul point d'accès à Client.objects.
=============================================================================
"""

from .models import Client


class ClientRepository:
    @staticmethod
    def get_all():
        return Client.objects.all()

    @staticmethod
    def get_by_id(client_id):
        return Client.objects.filter(pk=client_id).first()

    @staticmethod
    def get_by_code(code: str):
        # `all_objects`, pas `objects` : `code` est unique au niveau base sur
        # TOUTES les lignes (supprimées incluses — la suppression est logique,
        # voir SoftDeleteModel). Ne vérifier que les lignes actives laisserait
        # passer un code déjà pris par une ligne supprimée, et ferait échouer
        # la création avec une IntegrityError brute (500) plutôt qu'un message
        # de validation propre.
        return Client.all_objects.filter(code=code).first()

    @staticmethod
    def create(**data) -> Client:
        return Client.objects.create(**data)

    @staticmethod
    def update(client: Client, **data) -> Client:
        for champ, valeur in data.items():
            setattr(client, champ, valeur)
        client.save()
        return client

    @staticmethod
    def delete(client: Client) -> None:
        client.delete()  # suppression logique (BaseModel / SoftDeleteModel)
