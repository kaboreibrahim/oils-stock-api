"""
=============================================================================
 apps/notifications/repositories.py
 Seul point d'accès à Notification.objects / PushSubscription.objects.
=============================================================================
"""

from django.utils import timezone

from .models import Notification, PushSubscription


class NotificationRepository:
    @staticmethod
    def creer_plusieurs(objets: list[Notification]) -> list[Notification]:
        # bulk_create renvoie les objets avec leur PK sur PostgreSQL.
        return Notification.objects.bulk_create(objets)

    @staticmethod
    def get_pour_utilisateur(utilisateur):
        return Notification.objects.filter(destinataire=utilisateur)

    @staticmethod
    def get_pour_utilisateur_par_id(utilisateur, notif_id):
        return Notification.objects.filter(destinataire=utilisateur, pk=notif_id).first()

    @staticmethod
    def compter_non_lus(utilisateur) -> int:
        return Notification.objects.filter(destinataire=utilisateur, lu=False).count()

    @staticmethod
    def marquer_lu(notification: Notification) -> Notification:
        notification.lu = True
        notification.lu_le = timezone.now()
        notification.save(update_fields=["lu", "lu_le"])
        return notification

    @staticmethod
    def marquer_tout_lu(utilisateur) -> int:
        return Notification.objects.filter(destinataire=utilisateur, lu=False).update(
            lu=True, lu_le=timezone.now(),
        )


class PushSubscriptionRepository:
    @staticmethod
    def upsert(*, utilisateur, endpoint: str, p256dh: str, auth: str, user_agent: str = "") -> PushSubscription:
        # Par endpoint : le même navigateur qui se réabonne ne crée pas de doublon,
        # et un endpoint qui changerait de propriétaire est réattribué proprement.
        abonnement, _ = PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={"utilisateur": utilisateur, "p256dh": p256dh, "auth": auth, "user_agent": user_agent},
        )
        return abonnement

    @staticmethod
    def get_pour_utilisateurs(utilisateurs):
        return PushSubscription.objects.filter(utilisateur__in=utilisateurs).select_related("utilisateur")

    @staticmethod
    def supprimer_par_endpoint(utilisateur, endpoint: str) -> int:
        supprimes, _ = PushSubscription.objects.filter(utilisateur=utilisateur, endpoint=endpoint).delete()
        return supprimes

    @staticmethod
    def supprimer(abonnement: PushSubscription) -> None:
        abonnement.delete()  # suppression réelle (UUIDModel, pas de soft-delete)
