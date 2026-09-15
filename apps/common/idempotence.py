"""
=============================================================================
 apps/common/idempotence.py
 Rejeu idempotent d'une écriture, à l'aide d'une clé cliente optionnelle
 (en-tête Idempotency-Key envoyé par le moteur de synchro hors-ligne du
 frontend — Phase 2 PWA). Fonction pure appelée explicitement en tête de
 chaque méthode de vue concernée — pas de mixin, pas de dispatch() surchargé,
 cohérent avec l'absence de ViewSet de base partagée dans ce projet.
=============================================================================
"""

from collections.abc import Callable
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from .repositories import IdempotencyRecordRepository


def executer_avec_idempotence(
    request,
    cle_fournie: str | None,
    executer: Callable[[], tuple[int, Any]],
) -> tuple[int, Any]:
    """`executer` : callable sans argument -> (status_code, corps_json_safe).

    Si `cle_fournie` est None, exécute normalement (comportement actuel,
    zéro risque pour les tests existants — la clé est optionnelle, seul le
    moteur de synchro hors-ligne l'envoie).

    `executer` peut lever ValidationError/DoesNotExist : on les laisse se
    propager SANS les intercepter ici — la transaction (donc aussi
    l'insertion de l'IdempotencyRecord) est alors annulée en bloc, ce qui est
    correct : un rejet métier n'a aucun effet de bord, donc rien à mémoriser ;
    un simple retry avec la même clé ré-exécutera `executer` proprement.
    """
    if not cle_fournie:
        return executer()

    with transaction.atomic():
        record, cree = IdempotencyRecordRepository.verrouiller_ou_creer(
            utilisateur=request.user, cle=cle_fournie,
            methode=request.method, chemin=request.path,
        )
        if not cree:
            if record.methode != request.method or record.chemin != request.path:
                raise ValidationError(
                    "Cette clé d'idempotence a déjà été utilisée pour une opération différente."
                )
            if record.statut_code is None:
                # Extrêmement rare : une requête concurrente porteuse de la
                # même clé est en cours d'exécution (ex. deux onglets qui
                # rejouent la même opération en même temps).
                raise ValidationError("Cette opération est déjà en cours de traitement — réessayez.")
            return record.statut_code, record.corps

        statut_code, corps = executer()
        IdempotencyRecordRepository.enregistrer_reponse(record, statut_code=statut_code, corps=corps)
        return statut_code, corps
