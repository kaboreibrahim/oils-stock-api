"""
=============================================================================
 apps/sorties/services.py
 Règles métier des sorties. Aucun accès direct à l'ORM ici : tout passe par
 SortieRepository / LigneSortieRepository (ce domaine) et par
 UniteStockRepository / MouvementStockService (apps.stock) pour faire passer
 les unités EN_STOCK <-> SORTIE et écrire le journal des mouvements.
=============================================================================
"""

import logging
from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.models import HistoriqueAction
from apps.common.services import HistoriqueActionService
from apps.notifications.services import NotificationService
from apps.stock.models import StatutStock, TypeMouvement
from apps.stock.repositories import UniteStockRepository
from apps.stock.services import MouvementStockService

from .models import LigneSortie, Sortie, StatutSortie
from .repositories import LigneSortieRepository, SortieRepository

logger = logging.getLogger("apps.sorties")

# Filet de sécurité contre une collision de référence concurrente (bascule
# d'année, tout premier enregistrement, ou deux tentatives de rejeu
# idempotent simultanées — voir _generer_reference()).
NB_TENTATIVES_REFERENCE = 3


class SortieService:
    def __init__(
        self,
        repo: SortieRepository | None = None,
        lignes: LigneSortieRepository | None = None,
        unites: UniteStockRepository | None = None,
        mouvements: MouvementStockService | None = None,
        historique: HistoriqueActionService | None = None,
        notifications: NotificationService | None = None,
    ):
        self.repo = repo or SortieRepository()
        self.lignes = lignes or LigneSortieRepository()
        self.unites = unites or UniteStockRepository()
        self.mouvements = mouvements or MouvementStockService()
        self.historique = historique or HistoriqueActionService()
        self.notifications = notifications or NotificationService()

    # ── Lecture ──────────────────────────────────────────────────────────

    def lister(self):
        return self.repo.get_all()

    def obtenir(self, sortie_id) -> Sortie:
        sortie = self.repo.get_by_id(sortie_id)
        if sortie is None:
            raise Sortie.DoesNotExist("Sortie introuvable.")
        return sortie

    def lister_lignes(self, sortie: Sortie):
        return self.lignes.get_all_for_sortie(sortie)

    # ── En-tête ──────────────────────────────────────────────────────────

    def creer(self, donnees: dict, utilisateur) -> Sortie:
        sortie = None
        for _ in range(NB_TENTATIVES_REFERENCE):
            try:
                with transaction.atomic():  # savepoint — isole une collision de référence concurrente
                    reference = self._generer_reference()
                    sortie = self.repo.create(
                        reference=reference,
                        cree_par=utilisateur if getattr(utilisateur, "is_authenticated", False) else None,
                        **donnees,
                    )
                break
            except IntegrityError:
                sortie = None
                continue
        if sortie is None:
            raise ValidationError("Impossible de générer une référence de sortie unique — veuillez réessayer.")
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.CREATION, app="sorties",
            objet_type="Sortie", objet_id=sortie.id, resume=f"Création de la sortie {sortie.reference}",
        )
        logger.info("Sortie créée : %s", sortie.reference)
        return sortie

    def modifier(self, sortie: Sortie, donnees: dict, utilisateur) -> Sortie:
        self._verifier_brouillon(sortie, "modifier l'en-tête")
        sortie = self.repo.update(sortie, **donnees)
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.MODIFICATION, app="sorties",
            objet_type="Sortie", objet_id=sortie.id, resume=f"Modification de la sortie {sortie.reference}",
        )
        return sortie

    def supprimer(self, sortie: Sortie, utilisateur) -> None:
        self._verifier_brouillon(sortie, "supprimer")
        reference = sortie.reference
        self.repo.delete(sortie)
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.SUPPRESSION, app="sorties",
            objet_type="Sortie", objet_id=sortie.id, resume=f"Suppression de la sortie {reference}",
        )

    # ── Lignes ───────────────────────────────────────────────────────────

    def ajouter_ligne(self, sortie: Sortie, numero_serie: str, utilisateur, fournisseur=None) -> LigneSortie:
        self._verifier_brouillon(sortie, "ajouter une unité")
        unite = self._resoudre_unite_en_stock(numero_serie, fournisseur)

        ligne = self.lignes.create(sortie=sortie, unite_stock=unite)
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.MODIFICATION, app="sorties",
            objet_type="Sortie", objet_id=sortie.id,
            resume=f"Ajout de {unite.numero_serie} à la sortie {sortie.reference}",
        )
        return ligne

    def retirer_ligne(self, sortie: Sortie, ligne_id, utilisateur) -> None:
        self._verifier_brouillon(sortie, "retirer une unité")
        ligne = self.lignes.get_by_id(sortie, ligne_id)
        if ligne is None:
            raise LigneSortie.DoesNotExist("Ligne de sortie introuvable.")
        numero_serie = ligne.unite_stock.numero_serie
        self.lignes.delete(ligne)
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.MODIFICATION, app="sorties",
            objet_type="Sortie", objet_id=sortie.id,
            resume=f"Retrait de {numero_serie} de la sortie {sortie.reference}",
        )

    # ── Cycle de vie ─────────────────────────────────────────────────────

    def valider(self, sortie: Sortie, utilisateur) -> Sortie:
        self._verifier_brouillon(sortie, "valider")
        lignes = list(self.lignes.get_all_for_sortie(sortie))
        if not lignes:
            raise ValidationError("Impossible de valider une sortie sans aucune unité.")

        date_mouvement = timezone.make_aware(datetime.combine(sortie.date_sortie, time.min))

        # État des seuils AVANT la validation — pour détecter un franchissement
        # (avant > seuil, après <= seuil) une fois les unités sorties.
        fournisseurs_par_cle = {
            (ligne.unite_stock.fournisseur_id, ligne.unite_stock.type_article): ligne.unite_stock.fournisseur
            for ligne in lignes
        }
        etat_seuils_avant = self.notifications.capturer_etat_seuils(fournisseurs_par_cle)

        with transaction.atomic():
            for ligne in lignes:
                unite = ligne.unite_stock
                if unite.statut != StatutStock.EN_STOCK:
                    # Filet de sécurité : chaque ajout vérifie déjà le statut, mais une
                    # unité a pu sortir entre-temps par une autre sortie concurrente.
                    raise ValidationError(
                        f"L'unité {unite.numero_serie} n'est plus en stock — retirez-la de cette sortie."
                    )
                unite.statut = StatutStock.SORTIE
                unite.sortie = sortie
                unite.date_sortie = sortie.date_sortie
                unite.save(update_fields=["statut", "sortie", "date_sortie", "updated_at"])
                self.mouvements.enregistrer(
                    unite_stock=unite, type_mouvement=TypeMouvement.SORTIE,
                    utilisateur=utilisateur, sortie=sortie,
                    commentaire=f"Sortie {sortie.reference}", date_mouvement=date_mouvement,
                )

            sortie = self.repo.update(
                sortie, statut=StatutSortie.VALIDEE,
                valide_par=utilisateur if getattr(utilisateur, "is_authenticated", False) else None,
                valide_le=timezone.now(),
            )

        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.VALIDATION, app="sorties",
            objet_type="Sortie", objet_id=sortie.id,
            resume=f"Validation de la sortie {sortie.reference} ({len(lignes)} unité(s))",
        )
        self.notifications.notifier_sortie_validee(
            sortie=sortie, etat_avant=etat_seuils_avant, nombre=len(lignes),
        )
        logger.info("Sortie validée : %s (%s unités)", sortie.reference, len(lignes))
        return sortie

    def annuler(self, sortie: Sortie, motif: str, utilisateur) -> Sortie:
        if sortie.statut != StatutSortie.VALIDEE:
            raise ValidationError("Seule une sortie validée peut être annulée.")
        motif = (motif or "").strip()
        if not motif:
            raise ValidationError("Le motif d'annulation est obligatoire.")

        with transaction.atomic():
            lignes = list(self.lignes.get_all_for_sortie(sortie))
            for ligne in lignes:
                unite = ligne.unite_stock
                unite.statut = StatutStock.EN_STOCK
                unite.sortie = None
                unite.date_sortie = None
                unite.save(update_fields=["statut", "sortie", "date_sortie", "updated_at"])
                self.mouvements.enregistrer(
                    unite_stock=unite, type_mouvement=TypeMouvement.ANNULATION_SORTIE,
                    utilisateur=utilisateur, sortie=sortie, commentaire=motif,
                )

            sortie = self.repo.update(
                sortie, statut=StatutSortie.ANNULEE, motif_annulation=motif,
                annule_par=utilisateur if getattr(utilisateur, "is_authenticated", False) else None,
                annule_le=timezone.now(),
            )

        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.ANNULATION, app="sorties",
            objet_type="Sortie", objet_id=sortie.id,
            resume=f"Annulation de la sortie {sortie.reference} — {motif}",
        )
        logger.info("Sortie annulée : %s", sortie.reference)
        return sortie

    # ── Utilitaires ──────────────────────────────────────────────────────

    def _resoudre_unite_en_stock(self, numero_serie: str, fournisseur=None):
        numero_serie = (numero_serie or "").strip()
        if not numero_serie:
            raise ValidationError("Le numéro de série est obligatoire.")
        candidats_qs = self.unites.get_all().filter(numero_serie=numero_serie, statut=StatutStock.EN_STOCK)
        if fournisseur is not None:
            candidats_qs = candidats_qs.filter(fournisseur=fournisseur)
        candidats = list(candidats_qs[:2])
        if not candidats:
            raise ValidationError(f"Aucune unité en stock avec le numéro de série « {numero_serie} ».")
        if len(candidats) > 1:
            raise ValidationError(
                f"Plusieurs unités en stock partagent le numéro « {numero_serie} » "
                "(fournisseurs différents) — précisez le fournisseur."
            )
        return candidats[0]

    def _verifier_brouillon(self, sortie: Sortie, action: str) -> None:
        if sortie.statut != StatutSortie.BROUILLON:
            raise ValidationError(f"Impossible de {action} : la sortie n'est plus au statut brouillon.")

    def _generer_reference(self) -> str:
        annee = timezone.now().year
        prefixe = f"SOR-{annee}-"
        dernier = self.repo.get_dernier_numero(prefixe)
        dernier_num = int(dernier.reference.rsplit("-", 1)[-1]) if dernier else 0
        return f"{prefixe}{dernier_num + 1:04d}"
