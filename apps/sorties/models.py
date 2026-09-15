"""
=============================================================================
 apps/sorties/models.py
=============================================================================
"""

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel, UUIDModel


class StatutSortie(models.TextChoices):
    BROUILLON = "BROUILLON", "Brouillon"
    VALIDEE = "VALIDEE", "Validée"
    ANNULEE = "ANNULEE", "Annulée"


class Sortie(BaseModel):
    """Un bon de sortie : en-tête client/projet/TRD, une ou plusieurs unités
    (LigneSortie). Cycle : BROUILLON (en construction) -> VALIDEE (unités
    passées SORTIE, mouvements écrits, bon de sortie disponible) -> ANNULEE
    (toutes les unités reviennent EN_STOCK, motif obligatoire). Rien n'est
    supprimé : une sortie annulée reste consultable (§06 du dossier de
    conception).
    """

    reference = models.CharField(
        "référence", max_length=30, unique=True, editable=False,
        help_text="Générée automatiquement, ex. SOR-2026-0001.",
    )
    client = models.ForeignKey(
        "clients.Client", verbose_name="client", on_delete=models.PROTECT, related_name="sorties",
    )
    projet = models.CharField(
        "projet", max_length=200, help_text="Texte libre, autocomplété depuis l'historique.",
    )
    trd = models.CharField("TRD", max_length=100, help_text="Référence saisie à chaque sortie.")
    date_sortie = models.DateField("date de sortie")
    statut = models.CharField(
        "statut", max_length=20, choices=StatutSortie.choices, default=StatutSortie.BROUILLON,
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="créée par", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sorties_creees",
    )
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="validée par", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sorties_validees",
    )
    annule_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="annulée par", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="sorties_annulees",
    )
    valide_le = models.DateTimeField("validée le", null=True, blank=True)
    annule_le = models.DateTimeField("annulée le", null=True, blank=True)
    motif_annulation = models.CharField("motif d'annulation", max_length=255, blank=True)
    notes = models.TextField("notes", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_sortie", "-created_at"]
        verbose_name = "sortie"
        verbose_name_plural = "sorties"

    def __str__(self) -> str:
        return self.reference


class LigneSortie(UUIDModel):
    """Une unité sur un bon de sortie.

    Suppression réelle, volontairement PAS de suppression logique ici (à la
    différence du reste du projet) : une ligne retirée d'un brouillon n'a
    jamais représenté un mouvement de stock, il n'y a donc rien à tracer.
    Le journal d'audit métier commence à la validation (voir MouvementStock).
    """

    sortie = models.ForeignKey(Sortie, verbose_name="sortie", on_delete=models.CASCADE, related_name="lignes")
    unite_stock = models.ForeignKey(
        "stock.UniteStock", verbose_name="unité de stock", on_delete=models.PROTECT, related_name="lignes_sortie",
    )
    ajoute_le = models.DateTimeField("ajoutée le", auto_now_add=True)

    class Meta:
        verbose_name = "ligne de sortie"
        verbose_name_plural = "lignes de sortie"
        ordering = ["ajoute_le"]
        constraints = [
            models.UniqueConstraint(fields=["sortie", "unite_stock"], name="sorties_lignesortie_unique_par_sortie"),
        ]

    def __str__(self) -> str:
        return f"{self.unite_stock.numero_serie} — {self.sortie.reference}"
