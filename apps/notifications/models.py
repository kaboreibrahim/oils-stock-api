"""
=============================================================================
 apps/notifications/models.py
 Deux modèles, tous deux immuables au sens « pas de suppression logique »
 (comme HistoriqueAction, ils étendent UUIDModel et non BaseModel) — seul
 l'état lu/non-lu d'une Notification change après création.
=============================================================================
"""

from django.conf import settings
from django.db import models

from apps.common.models import UUIDModel


class Notification(UUIDModel):
    """Une ligne par destinataire (l'état lu est par utilisateur). Créées en
    lot par NotificationService lors de la validation d'une sortie / réception
    ou d'un franchissement de seuil de réapprovisionnement."""

    class Type(models.TextChoices):
        MOUVEMENT_ENTREE = "MOUVEMENT_ENTREE", "Réception validée"
        MOUVEMENT_SORTIE = "MOUVEMENT_SORTIE", "Sortie validée"
        SEUIL_ATTEINT = "SEUIL_ATTEINT", "Seuil de réapprovisionnement atteint"
        STOCK_EPUISE = "STOCK_EPUISE", "Stock épuisé"

    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="destinataire",
        on_delete=models.CASCADE, related_name="notifications",
    )
    type = models.CharField("type", max_length=20, choices=Type.choices)
    titre = models.CharField("titre", max_length=200)
    corps = models.CharField("corps", max_length=500, blank=True)
    lien = models.CharField(
        "lien", max_length=200, blank=True,
        help_text="Chemin in-app vers l'objet concerné (ex. /sorties/<id>, /previsions).",
    )
    lu = models.BooleanField("lu", default=False)
    lu_le = models.DateTimeField("lu le", null=True, blank=True)
    created_at = models.DateTimeField("créée le", auto_now_add=True)

    class Meta:
        verbose_name = "notification"
        verbose_name_plural = "notifications"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["destinataire", "lu", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.get_type_display()} → {self.destinataire_id} ({self.created_at:%Y-%m-%d %H:%M})"


class PushSubscription(UUIDModel):
    """Un abonnement web push par appareil/navigateur d'un utilisateur.
    `endpoint` est l'URL fournie par le service de push du navigateur ; unique
    au niveau base (un même endpoint ne peut appartenir qu'à un abonnement)."""

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="utilisateur",
        on_delete=models.CASCADE, related_name="abonnements_push",
    )
    endpoint = models.TextField("endpoint", unique=True)
    p256dh = models.CharField("clé publique (p256dh)", max_length=255)
    auth = models.CharField("secret (auth)", max_length=255)
    user_agent = models.CharField("user agent", max_length=300, blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        verbose_name = "abonnement web push"
        verbose_name_plural = "abonnements web push"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.utilisateur_id} — {self.endpoint[:60]}"
