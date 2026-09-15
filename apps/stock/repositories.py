"""
=============================================================================
 apps/stock/repositories.py
 Seul point d'accès à UniteStock.objects / MouvementStock.objects.
=============================================================================
"""

from django.db.models import Q

from .models import MouvementStock, StatutStock, UniteStock


class UniteStockRepository:
    @staticmethod
    def get_all():
        return UniteStock.objects.select_related("fournisseur", "sortie", "reception").all()

    @staticmethod
    def compter_en_stock(fournisseur, type_article) -> int:
        """Nombre d'unités actuellement EN_STOCK pour ce couple fournisseur/type.
        `.objects` direct (filtre `.filter(...)`, pas une relation inverse) — le
        piège soft-delete de FournisseurRepository.get_all() ne s'applique pas ici."""
        return UniteStock.objects.filter(
            fournisseur=fournisseur, type_article=type_article, statut=StatutStock.EN_STOCK,
        ).count()

    @staticmethod
    def get_by_id(unite_id):
        return UniteStockRepository.get_all().filter(pk=unite_id).first()

    @staticmethod
    def get_by_numero_serie(fournisseur, numero_serie: str):
        return UniteStock.objects.filter(fournisseur=fournisseur, numero_serie=numero_serie).first()

    @staticmethod
    def get_by_code_ou_numero(valeur: str):
        """Résolution scan (§07 du dossier de conception) : `code_interne` OU
        `numero_serie` — peut renvoyer plusieurs lignes (numéro partagé entre
        fournisseurs, voir §02/§04), à l'appelant de désambiguïser."""
        return UniteStockRepository.get_all().filter(
            Q(code_interne=valeur) | Q(numero_serie=valeur)
        )

    @staticmethod
    def create(**data) -> UniteStock:
        return UniteStock.objects.create(**data)


class MouvementStockRepository:
    @staticmethod
    def get_all():
        return MouvementStock.objects.select_related("unite_stock", "sortie", "reception", "utilisateur").all()

    @staticmethod
    def get_by_id(mouvement_id):
        return MouvementStockRepository.get_all().filter(pk=mouvement_id).first()

    @staticmethod
    def create(**data) -> MouvementStock:
        return MouvementStock.objects.create(**data)
