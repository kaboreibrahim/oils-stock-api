"""
=============================================================================
 apps/users/models.py
 Utilisateur applicatif — rôle + suppression logique. Manager recomposé pour
 garder create_user/create_superuser tout en filtrant les comptes supprimés.
=============================================================================
"""

import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils import timezone

from apps.common.models import SoftDeleteModel, SoftDeleteQuerySet, UUIDModel


class UserManager(DjangoUserManager.from_queryset(SoftDeleteQuerySet)):
    """UserManager standard de Django (create_user/create_superuser) + suppression logique."""

    def get_queryset(self):
        return super().get_queryset().alive()


class UserAllObjectsManager(DjangoUserManager.from_queryset(SoftDeleteQuerySet)):
    """Comme UserManager, mais sans filtrer les comptes supprimés."""


class User(SoftDeleteModel, AbstractUser):
    """Utilisateur de l'application, avec un rôle qui pilote les permissions."""

    id = models.UUIDField(
        "Identifiant unique",
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrateur"
        MAGASINIER = "MAGASINIER", "Magasinier"
        LECTURE = "LECTURE", "Lecture seule"

    role = models.CharField(
        "rôle",
        max_length=20,
        choices=Role.choices,
        default=Role.LECTURE,
    )

    # Redéclarés ici (plutôt qu'hérités tels quels de SoftDeleteModel) pour que
    # `objects` conserve create_user/create_superuser tout en filtrant les
    # comptes supprimés ; `all_objects` donne accès à tout, supprimés inclus.
    objects = UserManager()
    all_objects = UserAllObjectsManager()

    class Meta(AbstractUser.Meta):
        pass

    @property
    def peut_ecrire(self) -> bool:
        """Réceptions, sorties, retours, saisie."""
        return self.role in {self.Role.ADMIN, self.Role.MAGASINIER}

    @property
    def est_admin(self) -> bool:
        return self.role == self.Role.ADMIN


class PasswordResetCode(UUIDModel):
    """Code à 6 chiffres envoyé par e-mail pour réinitialiser un mot de passe.

    Le code lui-même n'est jamais stocké en clair (`code_hache`, via les
    hashers Django). Éphémère par nature : pas de suppression logique ici,
    voir PasswordResetService pour la durée de vie, l'usage unique et la
    limite de tentatives.
    """

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="utilisateur",
        on_delete=models.CASCADE, related_name="codes_reinitialisation",
    )
    code_hache = models.CharField("code (haché)", max_length=128)
    date_expiration = models.DateTimeField("expire le")
    tentatives = models.PositiveSmallIntegerField("tentatives", default=0)
    utilise_le = models.DateTimeField("utilisé le", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "code de réinitialisation"
        verbose_name_plural = "codes de réinitialisation"
        ordering = ["-created_at"]

    @property
    def est_expire(self) -> bool:
        return timezone.now() >= self.date_expiration

    @property
    def est_utilisable(self) -> bool:
        return self.utilise_le is None and not self.est_expire and self.tentatives < 5

    def __str__(self) -> str:
        return f"Code pour {self.utilisateur} (expire {self.date_expiration:%Y-%m-%d %H:%M})"
