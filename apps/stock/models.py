"""
=============================================================================
 apps/stock/models.py
=============================================================================
"""

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel, UUIDModel


class TypeArticle(models.TextChoices):
    FLEXITANK = "FLEXITANK", "Flexitank"
    HEATING_PAD = "HEATING_PAD", "Heating pad"


class StatutStock(models.TextChoices):
    EN_STOCK = "EN_STOCK", "En stock"
    SORTIE = "SORTIE", "Sorti"


class UniteStock(BaseModel):
    """Une unité physique sérialisée (carton de flexitank ou heating pad).

    Cœur du modèle : une ligne = un objet physique = un numéro de série.
    Le numéro appartient au fournisseur (deux fournisseurs peuvent partager un
    même numéro) — voir la contrainte d'unicité ci-dessous et le §02/§04 du
    dossier de conception.

    `reception` et `sortie` sont toutes deux disponibles depuis le Jalon 3.
    """

    numero_serie = models.CharField(
        "numéro de série", max_length=100, db_index=True,
        help_text="Tel qu'imprimé par le fournisseur.",
    )
    code_interne = models.CharField(
        "code interne", max_length=32, unique=True, blank=True, null=True,
        help_text="Identifiant interne généré (QR), optionnel.",
    )
    type_article = models.CharField("type d'article", max_length=20, choices=TypeArticle.choices)
    fournisseur = models.ForeignKey(
        "fournisseurs.Fournisseur", verbose_name="fournisseur",
        on_delete=models.PROTECT, related_name="unites_stock",
    )
    statut = models.CharField(
        "statut", max_length=20, choices=StatutStock.choices, default=StatutStock.EN_STOCK,
    )
    sortie = models.ForeignKey(
        "sorties.Sortie", verbose_name="sortie en cours",
        on_delete=models.SET_NULL, null=True, blank=True, related_name="unites",
        help_text="Sortie non annulée en cours ; redevient nul après un retour ou une annulation.",
    )
    reception = models.ForeignKey(
        "receptions.Reception", verbose_name="réception",
        on_delete=models.PROTECT, null=True, blank=True, related_name="unites",
        help_text="Réception d'origine (arrivage, saisie manuelle ou reprise).",
    )
    date_entree = models.DateField("date d'entrée")
    date_sortie = models.DateField("date de sortie", null=True, blank=True)
    emplacement = models.CharField("emplacement", max_length=100, blank=True, help_text="Réservé v2.")
    reference_lot = models.CharField("référence de lot", max_length=100, blank=True)
    attributs = models.JSONField(
        "attributs", default=dict, blank=True,
        help_text="Capacité, type BL/BD, air vent, date de fabrication…",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "unité de stock"
        verbose_name_plural = "unités de stock"
        ordering = ["-date_entree", "numero_serie"]
        constraints = [
            models.UniqueConstraint(
                fields=["fournisseur", "numero_serie"],
                name="stock_unitestock_unique_numero_par_fournisseur",
            ),
        ]
        indexes = [
            models.Index(fields=["type_article", "statut"], name="stock_unite_type_statut_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.numero_serie} ({self.get_type_article_display()})"


class TypeMouvement(models.TextChoices):
    ENTREE = "ENTREE", "Entrée"
    SORTIE = "SORTIE", "Sortie"
    RETOUR = "RETOUR", "Retour"
    ANNULATION_ENTREE = "ANNULATION_ENTREE", "Annulation d'entrée"
    ANNULATION_SORTIE = "ANNULATION_SORTIE", "Annulation de sortie"


class MouvementStock(UUIDModel):
    """Journal d'audit du stock — immuable, jamais modifié ni supprimé après
    coup. Donne l'historique complet d'une unité en une requête (§04 du
    dossier de conception). Écrit uniquement par MouvementStockService.

    `reception` et `sortie` sont toutes deux disponibles depuis le Jalon 3.
    """

    unite_stock = models.ForeignKey(
        UniteStock, verbose_name="unité de stock", on_delete=models.CASCADE, related_name="mouvements",
    )
    type_mouvement = models.CharField("type de mouvement", max_length=20, choices=TypeMouvement.choices)
    date_mouvement = models.DateTimeField(
        "date du mouvement",
        help_text="Date métier de l'évènement (peut différer de la saisie, ex. un retour signalé après coup).",
    )
    reception = models.ForeignKey(
        "receptions.Reception", verbose_name="réception", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="mouvements",
        help_text="Réception à l'origine du mouvement (ENTREE, ANNULATION_ENTREE).",
    )
    sortie = models.ForeignKey(
        "sorties.Sortie", verbose_name="sortie", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="mouvements",
        help_text="Sortie à l'origine du mouvement (SORTIE, RETOUR, ANNULATION_SORTIE).",
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="utilisateur", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="mouvements_stock",
    )
    commentaire = models.CharField("commentaire", max_length=255, blank=True)
    created_at = models.DateTimeField("enregistré le", auto_now_add=True)

    class Meta:
        verbose_name = "mouvement de stock"
        verbose_name_plural = "mouvements de stock"
        ordering = ["-date_mouvement"]
        indexes = [models.Index(fields=["unite_stock", "date_mouvement"])]

    def __str__(self) -> str:
        return f"{self.type_mouvement} — {self.unite_stock.numero_serie} ({self.date_mouvement:%Y-%m-%d})"
