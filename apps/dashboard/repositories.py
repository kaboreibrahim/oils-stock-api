"""
=============================================================================
 apps/dashboard/repositories.py
 Seul point d'accès ORM pour les rapports du tableau de bord — lit
 Fournisseur, UniteStock et MouvementStock à la fois (raison pour laquelle
 cette logique vit ici plutôt que dans un des repositories existants, qui
 ne doivent chacun connaître que leur propre agrégat).

 Réutilise FournisseurRepository.get_all() pour les compteurs EN_STOCK par
 type (nb_flexitanks/nb_heating_pads) plutôt que de les recalculer ici —
 un seul endroit calcule "le stock actuel", partout dans l'appli.
=============================================================================
"""

from django.db.models import Count, DateField, OuterRef, Subquery
from django.db.models.functions import Cast, Coalesce, TruncMonth

from apps.fournisseurs.repositories import FournisseurRepository
from apps.stock.models import MouvementStock, StatutStock, TypeMouvement, UniteStock


class DashboardRepository:
    @staticmethod
    def get_fournisseurs():
        """Tous les fournisseurs, avec les compteurs EN_STOCK par type déjà
        annotés (nb_flexitanks/nb_heating_pads) — voir FournisseurRepository."""
        return FournisseurRepository.get_all()

    @staticmethod
    def compter_sorties_depuis(fournisseur, type_article, depuis) -> int:
        """Nombre de mouvements SORTIE pour ce fournisseur/type, depuis `depuis`
        (datetime) — base de la consommation moyenne journalière."""
        return MouvementStock.objects.filter(
            type_mouvement=TypeMouvement.SORTIE,
            date_mouvement__gte=depuis,
            unite_stock__fournisseur=fournisseur,
            unite_stock__type_article=type_article,
        ).count()

    @staticmethod
    def existe_sortie(fournisseur, type_article) -> bool:
        """Au moins une sortie déjà enregistrée pour ce fournisseur/type,
        sans limite de fenêtre temporelle — sert de garde-fou : sans aucun
        historique, une consommation moyenne de 0 ne veut rien dire, ce
        n'est pas la même chose qu'un vrai ralentissement récent."""
        return MouvementStock.objects.filter(
            type_mouvement=TypeMouvement.SORTIE,
            unite_stock__fournisseur=fournisseur,
            unite_stock__type_article=type_article,
        ).exists()

    @staticmethod
    def unites_en_stock_avec_date_reference():
        """Chaque unité EN_STOCK, avec sa date de référence pour la détection
        de stock dormant : la date de sa dernière sortie si elle en a déjà eu
        une (elle peut être repassée EN_STOCK après un retour), sinon sa date
        d'entrée. Première requête « dernière ligne liée par groupe » du
        projet — Subquery/OuterRef, pas de précédent existant à suivre.

        Cast obligatoire : date_mouvement est un DateTimeField, date_entree un
        DateField — Coalesce exige des types compatibles (PostgreSQL, le
        moteur réel de ce projet, refuse le mélange silencieusement accepté
        par SQLite).
        """
        derniere_sortie = (
            MouvementStock.objects
            .filter(unite_stock=OuterRef("pk"), type_mouvement=TypeMouvement.SORTIE)
            .order_by("-date_mouvement")
            .values("date_mouvement")[:1]
        )
        return (
            UniteStock.objects.filter(statut=StatutStock.EN_STOCK)
            .select_related("fournisseur")
            .annotate(derniere_sortie=Subquery(derniere_sortie))
            .annotate(
                date_reference=Coalesce(
                    Cast("derniere_sortie", output_field=DateField()),
                    "date_entree",
                    output_field=DateField(),
                ),
            )
        )

    @staticmethod
    def compter_sorties_par_mois_et_type(depuis):
        """Nombre de mouvements SORTIE groupés par mois (TruncMonth) et par
        type d'article, depuis `depuis` (date) — base du graphique "sorties
        mensuelles". Un mois sans aucune sortie n'apparaît simplement pas
        dans le résultat ; c'est au service de densifier les 12 mois."""
        return (
            MouvementStock.objects
            .filter(type_mouvement=TypeMouvement.SORTIE, date_mouvement__date__gte=depuis)
            .annotate(mois=TruncMonth("date_mouvement"))
            .values("mois", "unite_stock__type_article")
            .annotate(total=Count("id"))
        )
