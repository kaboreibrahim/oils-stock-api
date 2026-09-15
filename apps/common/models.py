"""
=============================================================================
 apps/common/models.py
 Socle partagé par toutes les apps métier — id UUID, suppression logique,
 journal d'audit générique. Aucune règle métier de domaine ici.
=============================================================================
"""

import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone


class UUIDModel(models.Model):
    """Base abstraite : identifiant UUID au lieu d'un entier auto-incrémenté."""

    id = models.UUIDField(
        "Identifiant unique",
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        """Suppression en masse : renseigne `deleted_at` au lieu d'effacer les lignes."""
        return super().update(deleted_at=timezone.now())

    def hard_delete(self):
        """Suppression réelle en base — à utiliser sciemment seulement."""
        return super().delete()

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)


class SoftDeleteManager(models.Manager):
    """Manager par défaut : ne renvoie que les lignes non supprimées (admin inclus)."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()


class SoftDeleteModel(models.Model):
    """Suppression logique : `delete()` renseigne `deleted_at` au lieu d'effacer la ligne."""

    deleted_at = models.DateTimeField("supprimé le", null=True, blank=True, editable=False)

    objects = SoftDeleteManager()   # lignes actives uniquement — manager par défaut
    all_objects = models.Manager()  # toutes les lignes, supprimées incluses

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def delete(self, using=None, keep_parents=False, hard=False):
        """Par défaut, suppression logique. `hard=True` pour une vraie suppression."""
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at"])
        return (1, {self.__class__._meta.label: 1})

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])


class BaseModel(UUIDModel, SoftDeleteModel):
    """Base commune aux modèles métier : identifiant UUID + suppression logique."""

    class Meta:
        abstract = True


class HistoriqueAction(UUIDModel):
    """Journal d'audit générique — une ligne par action métier notable, tous
    domaines confondus. Alimenté uniquement via HistoriqueActionService,
    jamais modifié ni supprimé après coup (voir apps/common/admin.py)."""

    class Action(models.TextChoices):
        CREATION = "CREATION", "Création"
        MODIFICATION = "MODIFICATION", "Modification"
        SUPPRESSION = "SUPPRESSION", "Suppression"
        RESTAURATION = "RESTAURATION", "Restauration"
        VALIDATION = "VALIDATION", "Validation"
        ANNULATION = "ANNULATION", "Annulation"
        RETOUR = "RETOUR", "Retour"
        AUTRE = "AUTRE", "Autre"

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="utilisateur",
        on_delete=models.SET_NULL, null=True, blank=True, related_name="actions_historique",
    )
    action = models.CharField("action", max_length=20, choices=Action.choices)
    app = models.CharField("app", max_length=50, help_text="ex. fournisseurs, clients, stock")
    objet_type = models.CharField("type d'objet", max_length=100, help_text="ex. Fournisseur, UniteStock")
    objet_id = models.CharField("identifiant de l'objet", max_length=64)
    resume = models.CharField("résumé", max_length=255, blank=True)
    donnees = models.JSONField("données", default=dict, blank=True)
    date = models.DateTimeField("date", auto_now_add=True)

    class Meta:
        verbose_name = "historique d'action"
        verbose_name_plural = "historique des actions"
        ordering = ["-date"]
        indexes = [models.Index(fields=["app", "objet_type", "objet_id"])]

    def __str__(self) -> str:
        return f"[{self.date:%Y-%m-%d %H:%M}] {self.action} {self.app}.{self.objet_type}#{self.objet_id}"


class IdempotencyRecord(UUIDModel):
    """Mémorise la réponse d'une écriture rejouable via l'en-tête
    Idempotency-Key — un rejeu avec la même clé renvoie la réponse déjà
    produite au lieu de ré-exécuter l'opération (Phase 2 PWA — écriture
    hors-ligne : le moteur de synchro du frontend rejoue une requête dont il
    n'a jamais reçu de réponse). Remplie une seule fois (statut_code/corps)
    juste après l'exécution — voir apps.common.idempotence."""

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="utilisateur",
        on_delete=models.CASCADE, related_name="idempotency_records",
    )
    cle = models.CharField("clé d'idempotence", max_length=255)
    methode = models.CharField("méthode HTTP", max_length=10)
    chemin = models.CharField("chemin", max_length=255)
    statut_code = models.PositiveSmallIntegerField("code HTTP renvoyé", null=True, blank=True)
    # DjangoJSONEncoder (pas l'encodeur JSON par défaut) : certains serializers
    # DRF renvoient un UUID/Decimal/date bruts dans .data (ex. PrimaryKeyRelatedField.
    # to_representation() ne stringifie pas l'UUID — seul le rendu HTTP final de
    # DRF le fait, via son propre encodeur) ; sans cet encodeur, l'enregistrement
    # de la réponse plante et annule toute la transaction (voir apps.common.idempotence).
    corps = models.JSONField("corps de la réponse", default=dict, blank=True, encoder=DjangoJSONEncoder)
    date_creation = models.DateTimeField("créé le", auto_now_add=True)
    date_reponse = models.DateTimeField("réponse enregistrée le", null=True, blank=True)

    class Meta:
        verbose_name = "clé d'idempotence"
        verbose_name_plural = "clés d'idempotence"
        constraints = [
            models.UniqueConstraint(fields=["utilisateur", "cle"], name="uniq_idempotence_par_utilisateur"),
        ]
        indexes = [models.Index(fields=["date_creation"])]

    def __str__(self) -> str:
        return f"{self.methode} {self.chemin} — {self.cle}"
