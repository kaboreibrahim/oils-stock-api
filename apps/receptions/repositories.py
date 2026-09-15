"""
=============================================================================
 apps/receptions/repositories.py
 Seul point d'accès à Reception.objects / LigneReception.objects.
=============================================================================
"""

from django.db.models import Count

from .models import LigneReception, Reception


class ReceptionRepository:
    @staticmethod
    def get_all():
        # Un .annotate() avec agrégat ne réapplique pas automatiquement le tri
        # par défaut du modèle (voir apps.sorties.repositories, même piège) —
        # .order_by() explicite pour que la pagination reste stable.
        return (
            Reception.objects.select_related("fournisseur", "cree_par", "valide_par", "annule_par")
            .annotate(nb_lignes=Count("lignes", distinct=True))
            .order_by("-date_reception", "-created_at")
        )

    @staticmethod
    def get_by_id(reception_id):
        return ReceptionRepository.get_all().filter(pk=reception_id).first()

    @staticmethod
    def get_dernier_numero(prefixe: str):
        """Verrouille la dernière référence de l'année (utiliser sous
        transaction.atomic() côté appelant) pour générer la suivante sans collision."""
        return (
            Reception.all_objects.select_for_update()
            .filter(reference__startswith=prefixe)
            .order_by("-reference")
            .first()
        )

    @staticmethod
    def create(**data) -> Reception:
        return Reception.objects.create(**data)

    @staticmethod
    def update(reception: Reception, **data) -> Reception:
        for champ, valeur in data.items():
            setattr(reception, champ, valeur)
        reception.save()
        return reception

    @staticmethod
    def delete(reception: Reception) -> None:
        reception.delete()  # suppression logique (BaseModel / SoftDeleteModel)


class LigneReceptionRepository:
    @staticmethod
    def get_all_for_reception(reception: Reception):
        return (
            LigneReception.objects.select_related("fournisseur")
            .filter(reception=reception)
        )

    @staticmethod
    def get_by_id(reception: Reception, ligne_id):
        return LigneReceptionRepository.get_all_for_reception(reception).filter(pk=ligne_id).first()

    @staticmethod
    def create(**data) -> LigneReception:
        return LigneReception.objects.create(**data)

    @staticmethod
    def create_many(lignes: list[LigneReception]) -> list[LigneReception]:
        return LigneReception.objects.bulk_create(lignes)

    @staticmethod
    def delete(ligne: LigneReception) -> None:
        ligne.delete()  # suppression réelle, voir docstring de LigneReception
