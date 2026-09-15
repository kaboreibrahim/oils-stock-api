"""
=============================================================================
 apps/receptions/models.py
=============================================================================
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models

from apps.common.models import BaseModel, UUIDModel
from apps.stock.models import TypeArticle

TAILLE_MAX_FICHIER_OCTETS = 20 * 1024 * 1024  # 20 Mo — largement au-dessus d'un bordereau réel


def valider_taille_fichier(fichier) -> None:
    if fichier.size > TAILLE_MAX_FICHIER_OCTETS:
        raise ValidationError("Le fichier dépasse la taille maximale autorisée (20 Mo).")


class NatureReception(models.TextChoices):
    ARRIVAGE = "ARRIVAGE", "Arrivage"
    SAISIE = "SAISIE", "Saisie manuelle"
    REPRISE = "REPRISE", "Reprise de l'existant"


class StatutReception(models.TextChoices):
    BROUILLON = "BROUILLON", "Brouillon"
    VALIDEE = "VALIDEE", "Validée"
    ANNULEE = "ANNULEE", "Annulée"


class StatutLigneReception(models.TextChoices):
    OK = "OK", "OK"
    DOUBLON = "DOUBLON", "Doublon"
    FORMAT_INVALIDE = "FORMAT_INVALIDE", "Format invalide"
    A_VERIFIER = "A_VERIFIER", "À vérifier"


class SourceLigneReception(models.TextChoices):
    EXTRACTION = "EXTRACTION", "Extraction automatique"
    PLAGE = "PLAGE", "Plage"
    MANUEL = "MANUEL", "Saisie manuelle"
    REPRISE = "REPRISE", "Reprise"


class Reception(BaseModel):
    """Un document d'entrée (arrivage, saisie manuelle ou reprise de l'existant).

    Cycle : BROUILLON (lignes en cours de saisie/revue) -> VALIDEE (chaque
    ligne OK devient une UniteStock, mouvements ENTREE écrits) -> ANNULEE
    (les unités qu'elle a créées sont retirées, motif obligatoire). Rien
    n'est supprimé : une réception annulée reste consultable (§04/§05 du
    dossier de conception).

    `nature=ARRIVAGE` a enfin son écran depuis le Jalon 4 : le PDF est stocké
    dans `fichier` et lu par `apps.receptions.extraction` (pdfplumber, sans
    OCR — un PDF scanné sans couche texte devra attendre le Jalon 5, ou
    passer par la saisie manuelle déjà disponible).
    """

    reference = models.CharField(
        "référence", max_length=30, unique=True, editable=False,
        help_text="Générée automatiquement, ex. REC-2026-0001.",
    )
    nature = models.CharField("nature", max_length=20, choices=NatureReception.choices)
    fournisseur = models.ForeignKey(
        "fournisseurs.Fournisseur", verbose_name="fournisseur",
        on_delete=models.PROTECT, null=True, blank=True, related_name="receptions",
        help_text="Requis pour un arrivage ou une saisie ; nul pour une reprise (fournisseur porté par chaque ligne).",
    )
    reference_fournisseur = models.CharField(
        "référence fournisseur", max_length=100, blank=True, help_text="Ex. EBT260407.",
    )
    fichier = models.FileField(
        "fichier", upload_to="receptions/%Y/%m/", null=True, blank=True,
        validators=[FileExtensionValidator(["pdf"]), valider_taille_fichier],
        help_text="PDF d'arrivage — requis pour nature=ARRIVAGE, absent sinon.",
    )
    date_reception = models.DateField("date de réception")
    statut = models.CharField(
        "statut", max_length=20, choices=StatutReception.choices, default=StatutReception.BROUILLON,
    )
    quantite_annoncee = models.PositiveIntegerField(
        "quantité annoncée", null=True, blank=True,
        help_text="Lue sur le document (ex. « 131 SETS »). Sert de contrôle de comptage, non bloquant.",
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="créée par", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="receptions_creees",
    )
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="validée par", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="receptions_validees",
    )
    annule_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="annulée par", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="receptions_annulees",
    )
    valide_le = models.DateTimeField("validée le", null=True, blank=True)
    annule_le = models.DateTimeField("annulée le", null=True, blank=True)
    motif_annulation = models.CharField("motif d'annulation", max_length=255, blank=True)
    notes = models.TextField("notes", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_reception", "-created_at"]
        verbose_name = "réception"
        verbose_name_plural = "réceptions"

    def __str__(self) -> str:
        return self.reference


class LigneReception(UUIDModel):
    """Une unité en attente sur une réception — brouillon, avant validation.

    Suppression réelle, volontairement PAS de suppression logique (même
    raisonnement que `apps.sorties.LigneSortie`) : une ligne retirée avant
    validation n'a jamais représenté un mouvement de stock.
    """

    reception = models.ForeignKey(Reception, verbose_name="réception", on_delete=models.CASCADE, related_name="lignes")
    numero_serie = models.CharField("numéro de série", max_length=100)
    fournisseur = models.ForeignKey(
        "fournisseurs.Fournisseur", verbose_name="fournisseur",
        on_delete=models.PROTECT, null=True, blank=True, related_name="lignes_reception",
        help_text="Renseigné pour une reprise (une ligne peut venir d'un fournisseur différent de l'en-tête) ; sinon hérité de la réception à la validation.",
    )
    type_article = models.CharField("type d'article", max_length=20, choices=TypeArticle.choices)
    statut_ligne = models.CharField(
        "statut", max_length=20, choices=StatutLigneReception.choices, default=StatutLigneReception.OK,
    )
    source = models.CharField("source", max_length=20, choices=SourceLigneReception.choices)
    ajoute_le = models.DateTimeField("ajoutée le", auto_now_add=True)

    class Meta:
        verbose_name = "ligne de réception"
        verbose_name_plural = "lignes de réception"
        ordering = ["ajoute_le"]

    def __str__(self) -> str:
        return f"{self.numero_serie} — {self.reception.reference}"
