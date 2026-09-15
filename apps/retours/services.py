"""
=============================================================================
 apps/retours/services.py
 Un retour n'est pas une entité persistée : c'est une opération qui fait
 revenir des UniteStock déjà SORTIE à EN_STOCK et écrit un MouvementStock
 RETOUR par unité (§04/§06 du dossier de conception — neuf tables au total,
 pas de table Retour). Compose les dépôts/services d'apps.stock, aucun accès
 direct à l'ORM ici.
=============================================================================
"""

import logging
from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.common.models import HistoriqueAction
from apps.common.services import HistoriqueActionService
from apps.stock.models import StatutStock, TypeMouvement
from apps.stock.repositories import UniteStockRepository
from apps.stock.services import MouvementStockService

logger = logging.getLogger("apps.retours")


class RetourService:
    def __init__(
        self,
        unites: UniteStockRepository | None = None,
        mouvements: MouvementStockService | None = None,
        historique: HistoriqueActionService | None = None,
    ):
        self.unites = unites or UniteStockRepository()
        self.mouvements = mouvements or MouvementStockService()
        self.historique = historique or HistoriqueActionService()

    def enregistrer(self, lignes: list[dict], date_retour, motif: str, utilisateur) -> list:
        motif = (motif or "").strip()
        if not motif:
            raise ValidationError("Le motif du retour est obligatoire.")
        if not lignes:
            raise ValidationError("Au moins une unité est requise.")

        # Résolution AVANT toute écriture : un seul numéro de série invalide
        # dans le lot doit refuser tout le retour, pas seulement cette ligne.
        unites = [self._resoudre_unite_sortie(l["numero_serie"], l.get("fournisseur")) for l in lignes]
        date_mouvement = timezone.make_aware(datetime.combine(date_retour, time.min))

        with transaction.atomic():
            for unite in unites:
                sortie_origine = unite.sortie
                unite.statut = StatutStock.EN_STOCK
                unite.sortie = None
                unite.save(update_fields=["statut", "sortie", "updated_at"])
                self.mouvements.enregistrer(
                    unite_stock=unite, type_mouvement=TypeMouvement.RETOUR,
                    utilisateur=utilisateur, sortie=sortie_origine,
                    commentaire=motif, date_mouvement=date_mouvement,
                )
                resume = f"Retour de {unite.numero_serie}"
                if sortie_origine is not None:
                    resume += f" (sortie {sortie_origine.reference})"
                resume += f" — {motif}"
                self.historique.enregistrer(
                    utilisateur=utilisateur, action=HistoriqueAction.Action.RETOUR, app="retours",
                    objet_type="UniteStock", objet_id=unite.id, resume=resume,
                )

        logger.info("Retour enregistré : %s unité(s), motif=%s", len(unites), motif)
        return unites

    def _resoudre_unite_sortie(self, numero_serie: str, fournisseur=None):
        numero_serie = (numero_serie or "").strip()
        if not numero_serie:
            raise ValidationError("Le numéro de série est obligatoire.")
        candidats_qs = self.unites.get_all().filter(numero_serie=numero_serie, statut=StatutStock.SORTIE)
        if fournisseur is not None:
            candidats_qs = candidats_qs.filter(fournisseur=fournisseur)
        candidats = list(candidats_qs[:2])
        if not candidats:
            raise ValidationError(f"Aucune unité sortie avec le numéro de série « {numero_serie} ».")
        if len(candidats) > 1:
            raise ValidationError(
                f"Plusieurs unités sorties partagent le numéro « {numero_serie} » "
                "(fournisseurs différents) — précisez le fournisseur."
            )
        return candidats[0]
