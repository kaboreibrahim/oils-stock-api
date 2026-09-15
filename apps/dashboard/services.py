"""
=============================================================================
 apps/dashboard/services.py
 Toutes les formules du tableau de bord — le repository ne fait que
 récupérer des lignes/agrégats, l'arithmétique vit ici (même répartition
 que le reste du projet, ex. FournisseurService._normaliser_code).
=============================================================================
"""

import math
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.stock.models import TypeArticle

from .repositories import DashboardRepository

# Fenêtre de calcul de la consommation moyenne journalière. Les sorties de ce
# projet sont groupées par projet client (Sortie.projet/trd), donc irrégulières
# dans le temps — une fenêtre de 30 jours se ferait fausser par une seule
# grosse sortie, une fenêtre de 365 jours lisserait un vrai changement récent
# de rythme. 90 jours (un trimestre) est aussi le seuil que l'utilisateur a
# lui-même choisi comme exemple pour le stock dormant — garder le même nombre
# aux deux endroits garde un seul modèle mental ("qu'est-ce qui a bougé ce
# trimestre ?") plutôt que deux fenêtres différentes à retenir.
LOOKBACK_JOURS_CONSOMMATION = 90


class DashboardService:
    def __init__(self, repo=None):
        self.repo = repo or DashboardRepository()

    # ------------------------------------------------------------------
    # Formules de base
    # ------------------------------------------------------------------

    def consommation_moyenne_journaliere(
        self, fournisseur, type_article, lookback_jours: int = LOOKBACK_JOURS_CONSOMMATION,
    ) -> float:
        depuis = timezone.now() - timedelta(days=lookback_jours)
        nb_sorties = self.repo.compter_sorties_depuis(fournisseur, type_article, depuis)
        return nb_sorties / lookback_jours  # lookback_jours est une constante > 0, jamais de division par zéro

    def seuil_effectif(self, fournisseur, type_article) -> tuple[int | None, str | None]:
        """(seuil, source) — source dans {"MANUEL", "CALCULE", None}. Le seuil
        manuel garde toujours la priorité (décision utilisateur) ; sinon,
        calculé uniquement si le fournisseur a un délai de livraison ET au
        moins un historique de sortie pour ce type (sans ça, pas de base de
        calcul — 0 sorties récentes ne veut rien dire sans historique)."""
        manuel = (
            fournisseur.seuil_reappro_flexitank if type_article == TypeArticle.FLEXITANK
            else fournisseur.seuil_reappro_heating_pad
        )
        if manuel is not None:
            return manuel, "MANUEL"

        if fournisseur.delai_livraison_jours is None:
            return None, None
        if not self.repo.existe_sortie(fournisseur, type_article):
            return None, None

        conso = self.consommation_moyenne_journaliere(fournisseur, type_article)
        stock_securite = (
            fournisseur.stock_securite_flexitank if type_article == TypeArticle.FLEXITANK
            else fournisseur.stock_securite_heating_pad
        ) or 0  # marge optionnelle — vide = 0, contrairement au délai qui bloque le calcul
        # ceil, jamais round : sous-estimer un point de commande prend un vrai risque de rupture.
        return math.ceil(conso * fournisseur.delai_livraison_jours + stock_securite), "CALCULE"

    @staticmethod
    def jours_avant_rupture(stock_actuel: int, conso: float) -> float | None:
        if conso <= 0:
            return None  # pas de rythme de sortie récent -> pas de projection fiable
        return stock_actuel / conso

    @staticmethod
    def date_commande_recommandee(stock_actuel: int, seuil: int | None, conso: float, aujourdhui: date) -> date | None:
        """Date à laquelle le stock (déclin linéaire au rythme `conso`)
        atteindrait le seuil — algébriquement le même déclencheur que
        « stock − conso×délai risque de passer sous la sécurité », puisque
        seuil = conso×délai + sécurité. `max(0, ...)` : déjà sous le seuil
        aujourd'hui -> recommander la commande aujourd'hui, pas une date passée."""
        if seuil is None or conso <= 0:
            return None
        jours_avant_seuil = (stock_actuel - seuil) / conso
        return aujourdhui + timedelta(days=max(0, math.floor(jours_avant_seuil)))

    # ------------------------------------------------------------------
    # Rapports exposés aux vues
    # ------------------------------------------------------------------

    def lister_seuils_reappro(self) -> list[dict]:
        resultats = []
        for fournisseur in self.repo.get_fournisseurs():
            for type_article, stock_actuel in (
                (TypeArticle.FLEXITANK, fournisseur.nb_flexitanks),
                (TypeArticle.HEATING_PAD, fournisseur.nb_heating_pads),
            ):
                seuil, source = self.seuil_effectif(fournisseur, type_article)
                resultats.append({
                    "fournisseur": fournisseur,
                    "type_article": type_article,
                    "stock_actuel": stock_actuel,
                    "seuil": seuil,
                    "source_seuil": source,
                    "en_alerte": seuil is not None and stock_actuel <= seuil,
                })
        return resultats

    def lister_stock_dormant(self, seuil_jours: int) -> list[dict]:
        if seuil_jours <= 0:
            raise ValidationError("Le seuil en jours doit être un nombre entier positif.")
        limite = timezone.now().date() - timedelta(days=seuil_jours)
        unites = self.repo.unites_en_stock_avec_date_reference().filter(date_reference__lte=limite)
        aujourdhui = timezone.now().date()

        resultat = []
        for unite in unites:
            cout = (
                unite.fournisseur.cout_unitaire_flexitank if unite.type_article == TypeArticle.FLEXITANK
                else unite.fournisseur.cout_unitaire_heating_pad
            )  # None si non configuré -> "—" côté serializer/frontend, jamais une valeur inventée
            resultat.append({
                "id": unite.id,
                "numero_serie": unite.numero_serie,
                "code_interne": unite.code_interne,
                "type_article": unite.type_article,
                "fournisseur": unite.fournisseur,
                "date_reference": unite.date_reference,
                "source_date": "DERNIERE_SORTIE" if unite.derniere_sortie else "ENTREE",
                "jours_ecoules": (aujourdhui - unite.date_reference).days,
                "valeur_immobilisee": cout,
            })
        return resultat

    def sorties_mensuelles(self) -> dict:
        aujourdhui = timezone.now().date()
        mois = self._douze_derniers_mois(aujourdhui)
        lignes = self.repo.compter_sorties_par_mois_et_type(mois[0])

        par_mois_type: dict[tuple[date, str], int] = {}
        for ligne in lignes:
            valeur_mois = ligne["mois"]
            cle_mois = valeur_mois.date() if hasattr(valeur_mois, "date") else valeur_mois
            par_mois_type[(cle_mois, ligne["unite_stock__type_article"])] = ligne["total"]

        flexitank = [par_mois_type.get((m, TypeArticle.FLEXITANK), 0) for m in mois]
        heating_pad = [par_mois_type.get((m, TypeArticle.HEATING_PAD), 0) for m in mois]

        return {
            "mois": [m.strftime("%Y-%m") for m in mois],
            "flexitank": flexitank,
            "heating_pad": heating_pad,
            "flexitank_moyenne_mobile": self._moyenne_mobile_3(flexitank),
            "heating_pad_moyenne_mobile": self._moyenne_mobile_3(heating_pad),
        }

    def previsions(self) -> list[dict]:
        aujourdhui = timezone.now().date()
        resultats = []
        for ligne in self.lister_seuils_reappro():
            fournisseur, type_article = ligne["fournisseur"], ligne["type_article"]
            conso = self.consommation_moyenne_journaliere(fournisseur, type_article)
            jours = self.jours_avant_rupture(ligne["stock_actuel"], conso)
            resultats.append({
                **ligne,
                "consommation_moyenne_journaliere": conso,
                "jours_avant_rupture": jours,
                "date_commande_recommandee": self.date_commande_recommandee(
                    ligne["stock_actuel"], ligne["seuil"], conso, aujourdhui,
                ),
            })
        # Ascendant sur jours_avant_rupture (rupture la plus proche en premier) ;
        # None (pas de rythme récent -> pas de projection) trié en dernier.
        resultats.sort(key=lambda r: (r["jours_avant_rupture"] is None, r["jours_avant_rupture"]))
        return resultats

    # ------------------------------------------------------------------
    @staticmethod
    def _douze_derniers_mois(reference: date) -> list[date]:
        mois, annee, m = [], reference.year, reference.month
        for _ in range(12):
            mois.append(date(annee, m, 1))
            m -= 1
            if m == 0:
                m, annee = 12, annee - 1
        return list(reversed(mois))

    @staticmethod
    def _moyenne_mobile_3(valeurs: list[int]) -> list[float | None]:
        return [None if i < 2 else sum(valeurs[i - 2:i + 1]) / 3 for i in range(len(valeurs))]
