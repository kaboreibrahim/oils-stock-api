"""
=============================================================================
 apps/notifications/services.py
 NotificationService — crée les notifications in-app (une ligne par
 destinataire) et tente un envoi web push vers chaque abonnement de chaque
 destinataire. Un échec d'envoi push n'interrompt JAMAIS l'appelant
 (validation d'une sortie / réception).

 Envoi synchrone dans la requête (pas de file d'attente dans ce projet) —
 borné par `timeout=5` par envoi, volumes internes faibles. Point
 d'évolution : `transaction.on_commit` + worker.
=============================================================================
"""

import json
import logging
from collections import defaultdict

from django.conf import settings
from pywebpush import WebPushException, webpush

from apps.dashboard.services import DashboardService
from apps.stock.models import TypeArticle
from apps.stock.repositories import UniteStockRepository
from apps.users.repositories import UserRepository

from .models import Notification
from .repositories import NotificationRepository, PushSubscriptionRepository

logger = logging.getLogger("apps.notifications")


class NotificationService:
    def __init__(self, repo=None, abonnements=None, utilisateurs=None, dashboard=None, unites=None):
        self.repo = repo or NotificationRepository()
        self.abonnements = abonnements or PushSubscriptionRepository()
        self.utilisateurs = utilisateurs or UserRepository()
        self.dashboard = dashboard or DashboardService()
        self.unites = unites or UniteStockRepository()

    # ------------------------------------------------------------------
    # Lecture / état (utilisé par la vue)
    # ------------------------------------------------------------------

    def lister(self, utilisateur):
        return self.repo.get_pour_utilisateur(utilisateur)

    def compter_non_lus(self, utilisateur) -> int:
        return self.repo.compter_non_lus(utilisateur)

    def marquer_lu(self, utilisateur, notif_id) -> Notification:
        notification = self.repo.get_pour_utilisateur_par_id(utilisateur, notif_id)
        if notification is None:
            raise Notification.DoesNotExist("Notification introuvable.")
        return self.repo.marquer_lu(notification)

    def marquer_tout_lu(self, utilisateur) -> int:
        return self.repo.marquer_tout_lu(utilisateur)

    # ------------------------------------------------------------------
    # Abonnements web push
    # ------------------------------------------------------------------

    def enregistrer_abonnement(self, *, utilisateur, endpoint: str, p256dh: str, auth: str, user_agent: str = ""):
        return self.abonnements.upsert(
            utilisateur=utilisateur, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=user_agent,
        )

    def supprimer_abonnement(self, *, utilisateur, endpoint: str) -> int:
        return self.abonnements.supprimer_par_endpoint(utilisateur, endpoint)

    # ------------------------------------------------------------------
    # Déclencheurs (appelés par SortieService / ReceptionService)
    # ------------------------------------------------------------------

    def capturer_etat_seuils(self, fournisseurs_par_cle: dict) -> dict:
        """Appelée AVANT le bloc atomic de la validation. `fournisseurs_par_cle`
        est {(fournisseur_id, type_article): Fournisseur}. Capture le seuil
        effectif et le stock actuel de chaque couple pour comparer après.

        Le seuil est capturé avant volontairement : sa branche CALCULE dépend
        des sorties récentes, que la validation est sur le point d'ajouter."""
        etat = {}
        for cle, fournisseur in fournisseurs_par_cle.items():
            _, type_article = cle
            seuil, _source = self.dashboard.seuil_effectif(fournisseur, type_article)
            etat[cle] = {
                "fournisseur": fournisseur,
                "type_article": type_article,
                "seuil": seuil,
                "avant": self.unites.compter_en_stock(fournisseur, type_article),
            }
        return etat

    def notifier_sortie_validee(self, *, sortie, etat_avant: dict, nombre: int) -> None:
        actifs = list(self.utilisateurs.lister_actifs())
        self._notifier(
            actifs, Notification.Type.MOUVEMENT_SORTIE,
            titre=f"Sortie {sortie.reference} validée",
            corps=f"{nombre} unité(s) sortie(s) du stock.",
            lien=f"/sorties/{sortie.id}",
        )
        for info in etat_avant.values():
            fournisseur, type_article = info["fournisseur"], info["type_article"]
            avant, seuil = info["avant"], info["seuil"]
            apres = self.unites.compter_en_stock(fournisseur, type_article)
            libelle = f"{fournisseur.code} · {TypeArticle(type_article).label}"

            if avant > 0 and apres == 0:
                self._notifier(
                    actifs, Notification.Type.STOCK_EPUISE,
                    titre=f"Stock épuisé — {libelle}",
                    corps=f"Il ne reste plus aucune unité de ce type pour {fournisseur.nom}.",
                    lien="/previsions",
                )
            elif seuil is not None and avant > seuil and apres <= seuil:
                self._notifier(
                    actifs, Notification.Type.SEUIL_ATTEINT,
                    titre=f"Seuil de réapprovisionnement atteint — {libelle}",
                    corps=f"Stock actuel : {apres} (seuil : {seuil}). À commander.",
                    lien="/previsions",
                )

    def notifier_reception_validee(self, *, reception, nombre: int) -> None:
        # Une réception ne fait qu'AJOUTER du stock — aucune alerte de seuil à
        # déclencher (elle peut seulement en résoudre une).
        actifs = list(self.utilisateurs.lister_actifs())
        self._notifier(
            actifs, Notification.Type.MOUVEMENT_ENTREE,
            titre=f"Réception {reception.reference} validée",
            corps=f"{nombre} unité(s) entrée(s) en stock.",
            lien=f"/receptions/{reception.id}",
        )

    # ------------------------------------------------------------------

    def _notifier(self, destinataires, type_notif, *, titre: str, corps: str = "", lien: str = "") -> None:
        objets = [
            Notification(destinataire=u, type=type_notif, titre=titre, corps=corps, lien=lien)
            for u in destinataires
        ]
        crees = self.repo.creer_plusieurs(objets)
        logger.info("notification: %s → %s destinataire(s) — %s", type_notif, len(crees), titre)

        abonnements_par_user = defaultdict(list)
        for abonnement in self.abonnements.get_pour_utilisateurs(destinataires):
            abonnements_par_user[abonnement.utilisateur_id].append(abonnement)

        payload = json.dumps({"titre": titre, "corps": corps, "lien": lien, "type": str(type_notif)})
        for notif in crees:
            for abonnement in abonnements_par_user.get(notif.destinataire_id, []):
                self._push_un(abonnement, payload)

    def _push_un(self, abonnement, payload: str) -> None:
        if not settings.VAPID_PRIVATE_KEY:
            logger.warning("VAPID non configuré — envoi web push ignoré")
            return
        try:
            webpush(
                subscription_info={
                    "endpoint": abonnement.endpoint,
                    "keys": {"p256dh": abonnement.p256dh, "auth": abonnement.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_CLAIM_EMAIL} if settings.VAPID_CLAIM_EMAIL else {},
                timeout=5,
            )
        except WebPushException as exc:
            statut = getattr(getattr(exc, "response", None), "status_code", None)
            if statut in (404, 410):
                # Abonnement mort côté service de push — on le nettoie.
                self.abonnements.supprimer(abonnement)
                logger.info("abonnement push périmé supprimé (%s)", statut)
            else:
                logger.warning("échec envoi web push (%s) : %s", statut, exc)
        except Exception as exc:  # noqa: BLE001 — un échec de push ne doit jamais casser la validation
            logger.warning("échec envoi web push (exception) : %s", exc)
