"""
=============================================================================
 apps/sorties/repositories.py
 Seul point d'accès à Sortie.objects / LigneSortie.objects.
=============================================================================
"""

from django.db.models import Count

from .models import LigneSortie, Sortie


class SortieRepository:
    @staticmethod
    def get_all():
        # Un .annotate() avec agrégat ne réapplique pas automatiquement le tri
        # par défaut du modèle (Django n'ordonne pas les requêtes groupées par
        # défaut) — .order_by() explicite pour que la pagination reste stable.
        return (
            Sortie.objects.select_related("client", "cree_par", "valide_par", "annule_par")
            .annotate(nb_unites=Count("lignes", distinct=True))
            .order_by("-date_sortie", "-created_at")
        )

    @staticmethod
    def get_by_id(sortie_id):
        return SortieRepository.get_all().filter(pk=sortie_id).first()

    @staticmethod
    def get_dernier_numero(prefixe: str):
        """Verrouille la dernière référence de l'année (utiliser sous
        transaction.atomic() côté appelant) pour générer la suivante sans collision."""
        return (
            Sortie.all_objects.select_for_update()
            .filter(reference__startswith=prefixe)
            .order_by("-reference")
            .first()
        )

    @staticmethod
    def create(**data) -> Sortie:
        return Sortie.objects.create(**data)

    @staticmethod
    def update(sortie: Sortie, **data) -> Sortie:
        for champ, valeur in data.items():
            setattr(sortie, champ, valeur)
        sortie.save()
        return sortie

    @staticmethod
    def delete(sortie: Sortie) -> None:
        sortie.delete()  # suppression logique (BaseModel / SoftDeleteModel)


class LigneSortieRepository:
    @staticmethod
    def get_all_for_sortie(sortie: Sortie):
        return (
            LigneSortie.objects.select_related("unite_stock", "unite_stock__fournisseur")
            .filter(sortie=sortie)
        )

    @staticmethod
    def get_by_id(sortie: Sortie, ligne_id):
        return LigneSortieRepository.get_all_for_sortie(sortie).filter(pk=ligne_id).first()

    @staticmethod
    def create(**data) -> LigneSortie:
        return LigneSortie.objects.create(**data)

    @staticmethod
    def delete(ligne: LigneSortie) -> None:
        ligne.delete()  # suppression réelle, voir docstring de LigneSortie
