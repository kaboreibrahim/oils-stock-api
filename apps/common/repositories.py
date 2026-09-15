"""
=============================================================================
 apps/common/repositories.py
 Seul point d'accès à HistoriqueAction.objects / IdempotencyRecord.objects.
=============================================================================
"""

from django.utils import timezone

from .models import HistoriqueAction, IdempotencyRecord


class HistoriqueActionRepository:
    @staticmethod
    def creer(**donnees) -> HistoriqueAction:
        return HistoriqueAction.objects.create(**donnees)

    @staticmethod
    def get_all():
        return HistoriqueAction.objects.select_related("utilisateur").all()

    @staticmethod
    def get_pour_objet(app: str, objet_type: str, objet_id):
        return HistoriqueActionRepository.get_all().filter(
            app=app, objet_type=objet_type, objet_id=str(objet_id),
        )


class IdempotencyRecordRepository:
    @staticmethod
    def verrouiller_ou_creer(*, utilisateur, cle: str, methode: str, chemin: str):
        """À appeler sous transaction.atomic() de l'appelant. get_or_create()
        encapsule déjà sa création dans un savepoint et refait un get() sous
        select_for_update() en cas d'IntegrityError concurrente — la course
        est donc protégée nativement par Django ici, contrairement à
        SortieRepository.get_dernier_numero (voir apps.sorties.services)."""
        return IdempotencyRecord.objects.select_for_update().get_or_create(
            utilisateur=utilisateur, cle=cle,
            defaults={"methode": methode, "chemin": chemin},
        )

    @staticmethod
    def enregistrer_reponse(record: IdempotencyRecord, *, statut_code: int, corps) -> None:
        record.statut_code = statut_code
        record.corps = corps
        record.date_reponse = timezone.now()
        record.save(update_fields=["statut_code", "corps", "date_reponse"])
