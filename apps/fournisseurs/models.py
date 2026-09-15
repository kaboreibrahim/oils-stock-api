"""
=============================================================================
 apps/fournisseurs/models.py
=============================================================================
"""

from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import BaseModel
from apps.stock.models import TypeArticle


class ModeExtraction(models.TextChoices):
    """Trois modes de lecture d'un PDF d'arrivage (§05 du dossier de conception)."""

    TABLEAU = "TABLEAU", "Tableau (en-têtes)"
    GRILLE = "GRILLE", "Grille (sans en-tête)"
    TEXTE = "TEXTE", "Texte libre"


class Fournisseur(BaseModel):
    """Fournisseur de flexitanks et/ou de heating pads."""

    code = models.CharField("code", max_length=20, unique=True, help_text="Ex. EBONT, DHL, LAF")
    nom = models.CharField("nom", max_length=200)
    pays = models.CharField("pays", max_length=100, blank=True)
    contact_nom = models.CharField("contact", max_length=200, blank=True)
    contact_email = models.EmailField("e-mail", blank=True)
    contact_tel = models.CharField("téléphone", max_length=50, blank=True)
    actif = models.BooleanField("actif", default=True)
    notes = models.TextField("notes", blank=True)

    # Profil d'extraction (Jalon 4) — géré via /fournisseurs/{id}/profil-extraction/,
    # pas via le CRUD général (voir apps/fournisseurs/views.py). Vide = pas de
    # profil : l'extraction retombe sur une détection générique, revue manuelle
    # assumée (statut A_VERIFIER systématique — voir apps.receptions.extraction).
    mode_extraction = models.CharField(
        "mode d'extraction", max_length=20, choices=ModeExtraction.choices, blank=True,
    )
    regex_numero_serie = models.CharField(
        "expression régulière — numéro de série", max_length=200, blank=True,
        help_text=r"Ex. 24E\d{10}A\d{3} (Ebont), \d{6} (DHL), 030926\d{7} (LAF).",
    )
    type_article_defaut = models.CharField(
        "type d'article par défaut", max_length=20, choices=TypeArticle.choices, blank=True,
        help_text="Appliqué aux lignes extraites de ce fournisseur si son catalogue est homogène.",
    )

    # Seuils de réapprovisionnement (demandé après coup) — un par type d'article
    # puisque le stock d'un même fournisseur peut être bas sur l'un et
    # confortable sur l'autre. Vide (`null`) = pas d'alerte configurée. Une
    # alerte se déclenche quand le nombre d'unités EN STOCK de ce type, pour ce
    # fournisseur, descend à ce niveau ou en dessous — voir
    # FournisseurRepository.get_all() (nb_flexitanks/nb_heating_pads).
    seuil_reappro_flexitank = models.PositiveIntegerField(
        "seuil de réapprovisionnement — flexitank", null=True, blank=True,
        help_text="Alerte si le nombre de Flexitanks en stock de ce fournisseur descend à ce niveau ou en dessous. Vide = pas d'alerte.",
    )
    seuil_reappro_heating_pad = models.PositiveIntegerField(
        "seuil de réapprovisionnement — heating pad", null=True, blank=True,
        help_text="Alerte si le nombre de Heating pads en stock de ce fournisseur descend à ce niveau ou en dessous. Vide = pas d'alerte.",
    )

    # Réapprovisionnement dynamique (demandé après coup, tableau de bord) —
    # sert à calculer un point de commande automatique (voir
    # apps.dashboard.services.DashboardService.seuil_effectif) quand aucun
    # seuil manuel ci-dessus n'est renseigné pour ce type. Le seuil manuel
    # garde toujours la priorité s'il est défini.
    delai_livraison_jours = models.PositiveIntegerField(
        "délai de livraison (jours)", null=True, blank=True,
        help_text=(
            "Délai moyen entre la commande et la réception, en jours. Sert au calcul du "
            "point de commande dynamique. Vide = seuil dynamique non calculable pour ce "
            "fournisseur (le seuil manuel ci-dessus reste utilisable, lui, indépendamment)."
        ),
    )
    stock_securite_flexitank = models.PositiveIntegerField(
        "stock de sécurité — flexitank", null=True, blank=True,
        help_text="Marge ajoutée au point de commande calculé. Vide = marge de 0.",
    )
    stock_securite_heating_pad = models.PositiveIntegerField(
        "stock de sécurité — heating pad", null=True, blank=True,
        help_text="Marge ajoutée au point de commande calculé. Vide = marge de 0.",
    )

    # Valorisation du stock (demandé après coup, vue « stock dormant ») —
    # optionnel : sans coût renseigné, la valeur immobilisée s'affiche « — »,
    # jamais une valeur inventée.
    # DecimalField n'a pas d'équivalent "PositiveDecimalField" intégré à
    # Django — validateur explicite pour refuser un coût négatif, comme
    # PositiveIntegerField le fait nativement pour les champs ci-dessus.
    cout_unitaire_flexitank = models.DecimalField(
        "coût unitaire — flexitank", max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Coût d'une unité Flexitank chez ce fournisseur. Vide = valeur immobilisée affichée « — » pour ce type.",
    )
    cout_unitaire_heating_pad = models.DecimalField(
        "coût unitaire — heating pad", max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Coût d'une unité Heating pad chez ce fournisseur. Vide = valeur immobilisée affichée « — » pour ce type.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom"]
        verbose_name = "fournisseur"
        verbose_name_plural = "fournisseurs"

    def __str__(self) -> str:
        return f"{self.nom} ({self.code})"

    @property
    def a_un_profil_extraction(self) -> bool:
        return bool(self.regex_numero_serie)
