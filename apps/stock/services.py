"""
=============================================================================
 apps/stock/services.py
 UniteStockService reste en lecture seule (les écritures passent par les
 autres apps métier, directement via UniteStockRepository : apps.sorties/
 apps.retours font passer une unité EN_STOCK <-> SORTIE, apps.receptions
 crée les unités à la validation).

 MouvementStockService est le seul point d'écriture du journal d'audit
 métier : toute app qui fait bouger une unité l'appelle pour tracer le
 mouvement, jamais MouvementStock.objects.create() directement.
=============================================================================
"""

import re

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.common.ocr import OcrIndisponible, ocriser_image

from .models import MouvementStock, UniteStock
from .repositories import MouvementStockRepository, UniteStockRepository

# Jetons ressemblant à un numéro de série sur une photo prise au scan mobile
# (Jalon 5) — aussi large que le repli générique de apps.receptions.extraction,
# gardé séparé pour ne pas faire dépendre apps.stock de apps.receptions
# (qui dépend déjà de apps.stock — un cycle sinon).
REGEX_CANDIDAT_SCAN = re.compile(r"\b[A-Z0-9]{5,24}\b")

# Au-delà, la photo est probablement trop bruitée (mauvais cadrage, reflet) —
# évite de renvoyer une liste interminable de faux positifs à l'utilisateur.
MAX_CANDIDATS_SCAN = 15


class UniteStockService:
    def __init__(self, repo: UniteStockRepository | None = None):
        self.repo = repo or UniteStockRepository()

    def lister(self):
        return self.repo.get_all()

    def obtenir(self, unite_id) -> UniteStock:
        unite = self.repo.get_by_id(unite_id)
        if unite is None:
            raise UniteStock.DoesNotExist("Unité de stock introuvable.")
        return unite

    def rechercher(self, valeur: str):
        """Résolution scan (§07) : `code_interne` ou `numero_serie` — peut
        renvoyer plusieurs unités (numéro partagé entre fournisseurs)."""
        valeur = (valeur or "").strip()
        if not valeur:
            return self.repo.get_all().none()
        return self.repo.get_by_code_ou_numero(valeur)

    def resoudre_candidats_image(self, image) -> list[dict]:
        """OCR d'une photo prise au scan mobile (Jalon 5) — renvoie les
        jetons détectés, chacun avec les unités qu'il résout (liste vide si
        aucune correspondance, l'utilisateur peut alors corriger à la main)."""
        try:
            texte = ocriser_image(image)
        except OcrIndisponible as exc:
            raise ValidationError(str(exc))

        vus: set[str] = set()
        candidats = []
        for jeton in REGEX_CANDIDAT_SCAN.findall(texte.upper()):
            if jeton in vus:
                continue
            vus.add(jeton)
            candidats.append(jeton)
            if len(candidats) >= MAX_CANDIDATS_SCAN:
                break

        resultats = [
            {"candidat": candidat, "unites": list(self.rechercher(candidat))}
            for candidat in candidats
        ]
        # Les jetons qui résolvent vraiment à une unité passent devant —
        # bien plus utile qu'un ordre purement basé sur la position dans le texte.
        resultats.sort(key=lambda r: len(r["unites"]) == 0)
        return resultats


class MouvementStockService:
    def __init__(self, repo: MouvementStockRepository | None = None):
        self.repo = repo or MouvementStockRepository()

    def lister(self):
        return self.repo.get_all()

    def obtenir(self, mouvement_id) -> MouvementStock:
        mouvement = self.repo.get_by_id(mouvement_id)
        if mouvement is None:
            raise MouvementStock.DoesNotExist("Mouvement de stock introuvable.")
        return mouvement

    def enregistrer(
        self, *, unite_stock, type_mouvement, utilisateur,
        sortie=None, reception=None, commentaire="", date_mouvement=None,
    ) -> MouvementStock:
        return self.repo.create(
            unite_stock=unite_stock,
            type_mouvement=type_mouvement,
            sortie=sortie,
            reception=reception,
            utilisateur=utilisateur if getattr(utilisateur, "is_authenticated", False) else None,
            commentaire=commentaire,
            date_mouvement=date_mouvement or timezone.now(),
        )
