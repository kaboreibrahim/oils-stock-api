"""
=============================================================================
 apps/fournisseurs/repositories.py
 Seul point d'accès à Fournisseur.objects — services et vues ne touchent
 jamais l'ORM directement.
=============================================================================
"""

from django.db.models import Count, Q

from apps.stock.models import StatutStock, TypeArticle

from .models import Fournisseur


class FournisseurRepository:
    @staticmethod
    def get_all():
        # nb_flexitanks/nb_heating_pads : répartition par type demandée sur la
        # liste des fournisseurs (pas seulement la fiche détail, qui les
        # calculait déjà via deux appels séparés à /unites/). Ne compte QUE les
        # unités actuellement EN_STOCK (pas le total historique) : c'est ce
        # nombre-là qui est comparé aux seuils de réapprovisionnement — les
        # deux doivent parler du même chiffre, sinon une alerte affichée à
        # côté d'un total qui ne bouge pas serait incompréhensible.
        #
        # `unites_stock__deleted_at__isnull=True` est INDISPENSABLE : la relation
        # inverse passe par le manager de base de UniteStock, qui n'applique PAS
        # le filtre de suppression logique (SoftDeleteModel) — sans cette
        # condition, les unités supprimées seraient comptées (bug réel :
        # DHL affichait 20 heating pads au lieu de 3, à cause de 17 unités
        # supprimées encore marquées statut=EN_STOCK).
        #
        # Un .annotate() avec agrégat ne réapplique pas automatiquement le tri
        # par défaut du modèle (déjà rencontré sur Sortie/Reception) —
        # .order_by() explicite.
        actif = Q(unites_stock__statut=StatutStock.EN_STOCK, unites_stock__deleted_at__isnull=True)
        return Fournisseur.objects.annotate(
            nb_flexitanks=Count(
                "unites_stock", filter=actif & Q(unites_stock__type_article=TypeArticle.FLEXITANK), distinct=True,
            ),
            nb_heating_pads=Count(
                "unites_stock", filter=actif & Q(unites_stock__type_article=TypeArticle.HEATING_PAD), distinct=True,
            ),
        ).order_by("nom")

    @staticmethod
    def get_by_id(fournisseur_id):
        # Passe par get_all() (pas Fournisseur.objects directement) pour que
        # la fiche détail garde elle aussi les compteurs annotés — même
        # pattern que SortieRepository.get_by_id.
        return FournisseurRepository.get_all().filter(pk=fournisseur_id).first()

    @staticmethod
    def get_by_code(code: str):
        # `all_objects`, pas `objects` : `code` est unique au niveau base sur
        # TOUTES les lignes (supprimées incluses — la suppression est logique,
        # voir SoftDeleteModel). Ne vérifier que les lignes actives laisserait
        # passer un code déjà pris par une ligne supprimée, et ferait échouer
        # la création avec une IntegrityError brute (500) plutôt qu'un message
        # de validation propre.
        return Fournisseur.all_objects.filter(code=code).first()

    @staticmethod
    def create(**data) -> Fournisseur:
        return Fournisseur.objects.create(**data)

    @staticmethod
    def update(fournisseur: Fournisseur, **data) -> Fournisseur:
        for champ, valeur in data.items():
            setattr(fournisseur, champ, valeur)
        fournisseur.save()
        return fournisseur

    @staticmethod
    def delete(fournisseur: Fournisseur) -> None:
        fournisseur.delete()  # suppression logique (BaseModel / SoftDeleteModel)
