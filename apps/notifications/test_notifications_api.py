"""
=============================================================================
 apps/notifications/test_notifications_api.py
 Une classe par thème. Vraies fixtures, validation pilotée via les endpoints
 HTTP des sorties/réceptions (comme apps/sorties/test_sortie_api.py).
=============================================================================
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from pywebpush import WebPushException
from rest_framework import status
from rest_framework.test import APITestCase

from apps.fournisseurs.models import Fournisseur
from apps.stock.models import StatutStock, TypeArticle, UniteStock

from .models import Notification, PushSubscription

User = get_user_model()


class NotifBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="n_admin", password="x", role=User.Role.ADMIN)
        self.magasinier = User.objects.create_user(username="n_mag", password="x", role=User.Role.MAGASINIER)
        self.lecteur = User.objects.create_user(username="n_lec", password="x", role=User.Role.LECTURE)
        self.fournisseur = Fournisseur.objects.create(code="DHL", nom="DHL")
        from apps.clients.models import Client

        self.client_obj = Client.objects.create(code="CLI", nom="Client Test")

    def _unite(self, numero, type_article=TypeArticle.FLEXITANK, fournisseur=None):
        return UniteStock.objects.create(
            numero_serie=numero, type_article=type_article,
            fournisseur=fournisseur or self.fournisseur, statut=StatutStock.EN_STOCK,
            date_entree=date.today(),
        )

    def _valider_sortie_avec(self, numeros: list[str], acteur=None):
        acteur = acteur or self.magasinier
        self.client.force_authenticate(user=acteur)
        creation = self.client.post(
            "/api/v1/sorties/",
            {"client": str(self.client_obj.pk), "projet": "P", "trd": "T", "date_sortie": "2026-09-10"},
        )
        self.assertEqual(creation.status_code, status.HTTP_201_CREATED, creation.data)
        sortie_id = creation.data["id"]
        for numero in numeros:
            r = self.client.post(f"/api/v1/sorties/{sortie_id}/lignes/", {"numero_serie": numero})
            self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        r = self.client.post(f"/api/v1/sorties/{sortie_id}/valider/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        return sortie_id


class NotificationsMouvementTests(NotifBase):
    def test_validation_sortie_notifie_chaque_utilisateur_actif_auteur_inclus(self):
        self._unite("F1")
        self._valider_sortie_avec(["F1"], acteur=self.magasinier)
        notifs = Notification.objects.filter(type=Notification.Type.MOUVEMENT_SORTIE)
        self.assertEqual(notifs.count(), 3)
        self.assertEqual(
            set(notifs.values_list("destinataire_id", flat=True)),
            {self.admin.id, self.magasinier.id, self.lecteur.id},
        )
        self.assertTrue(notifs.first().lien.startswith("/sorties/"))

    def test_utilisateur_inactif_non_notifie(self):
        self.lecteur.is_active = False
        self.lecteur.save(update_fields=["is_active"])
        self._unite("F1")
        self._valider_sortie_avec(["F1"])
        notifs = Notification.objects.filter(type=Notification.Type.MOUVEMENT_SORTIE)
        self.assertEqual(notifs.count(), 2)
        self.assertNotIn(self.lecteur.id, notifs.values_list("destinataire_id", flat=True))

    def test_validation_reception_notifie_entree_sans_alerte_seuil(self):
        self.client.force_authenticate(user=self.magasinier)
        creation = self.client.post(
            "/api/v1/receptions/",
            {"nature": "SAISIE", "fournisseur": str(self.fournisseur.pk), "date_reception": "2026-09-10"},
        )
        self.assertEqual(creation.status_code, status.HTTP_201_CREATED, creation.data)
        rid = creation.data["id"]
        r = self.client.post(
            f"/api/v1/receptions/{rid}/lignes/", {"numero_serie": "R1", "type_article": TypeArticle.FLEXITANK},
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        r = self.client.post(f"/api/v1/receptions/{rid}/valider/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)

        self.assertEqual(Notification.objects.filter(type=Notification.Type.MOUVEMENT_ENTREE).count(), 3)
        self.assertEqual(Notification.objects.filter(type=Notification.Type.SEUIL_ATTEINT).count(), 0)
        self.assertEqual(Notification.objects.filter(type=Notification.Type.STOCK_EPUISE).count(), 0)


class NotificationsSeuilTests(NotifBase):
    def test_seuil_atteint_sur_franchissement(self):
        self.fournisseur.seuil_reappro_flexitank = 2
        self.fournisseur.save(update_fields=["seuil_reappro_flexitank"])
        for n in ("F1", "F2", "F3"):
            self._unite(n)  # 3 en stock
        self._valider_sortie_avec(["F1"])  # 3 -> 2
        self.assertEqual(Notification.objects.filter(type=Notification.Type.SEUIL_ATTEINT).count(), 3)

    def test_pas_de_nouvelle_alerte_si_deja_sous_le_seuil(self):
        self.fournisseur.seuil_reappro_flexitank = 2
        self.fournisseur.save(update_fields=["seuil_reappro_flexitank"])
        for n in ("F1", "F2"):
            self._unite(n)  # 2 en stock (déjà == seuil)
        self._valider_sortie_avec(["F1"])  # 2 -> 1, pas un franchissement
        self.assertEqual(Notification.objects.filter(type=Notification.Type.SEUIL_ATTEINT).count(), 0)

    def test_stock_epuise_sur_passage_a_zero(self):
        self._unite("F1")
        self._valider_sortie_avec(["F1"])  # 1 -> 0
        epuise = Notification.objects.filter(type=Notification.Type.STOCK_EPUISE)
        self.assertEqual(epuise.count(), 3)
        self.assertEqual(epuise.first().lien, "/previsions")

    def test_epuise_prioritaire_sur_seuil(self):
        self.fournisseur.seuil_reappro_flexitank = 3
        self.fournisseur.save(update_fields=["seuil_reappro_flexitank"])
        for n in ("F1", "F2", "F3", "F4"):
            self._unite(n)
        self._valider_sortie_avec(["F1", "F2", "F3", "F4"])  # 4 -> 0
        self.assertEqual(Notification.objects.filter(type=Notification.Type.STOCK_EPUISE).count(), 3)
        self.assertEqual(Notification.objects.filter(type=Notification.Type.SEUIL_ATTEINT).count(), 0)


class NotificationsLectureApiTests(NotifBase):
    def _notif(self, destinataire, **kw):
        return Notification.objects.create(
            destinataire=destinataire, type=Notification.Type.MOUVEMENT_SORTIE,
            titre=kw.get("titre", "Test"), lu=kw.get("lu", False),
        )

    def test_liste_scopee_au_compte_courant(self):
        self._notif(self.admin, titre="A")
        self._notif(self.magasinier, titre="M")
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/v1/notifications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["titre"], "A")

    def test_filtre_non_lues(self):
        self._notif(self.admin, titre="lue", lu=True)
        self._notif(self.admin, titre="non lue", lu=False)
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/v1/notifications/?lu=false")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["titre"], "non lue")

    def test_non_lus_compte(self):
        self._notif(self.admin)
        self._notif(self.admin)
        self._notif(self.magasinier)
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/v1/notifications/non-lus/")
        self.assertEqual(response.data, {"count": 2})

    def test_marquer_lu_scope_et_404_sur_notif_d_un_autre(self):
        mienne = self._notif(self.admin)
        autre = self._notif(self.magasinier)
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(
            self.client.post(f"/api/v1/notifications/{autre.id}/marquer-lu/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        r = self.client.post(f"/api/v1/notifications/{mienne.id}/marquer-lu/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        mienne.refresh_from_db()
        self.assertTrue(mienne.lu)
        self.assertIsNotNone(mienne.lu_le)

    def test_marquer_tout_lu(self):
        self._notif(self.admin)
        self._notif(self.admin)
        self._notif(self.magasinier)
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/v1/notifications/marquer-tout-lu/")
        self.assertEqual(r.data, {"count": 2})
        self.assertEqual(Notification.objects.filter(destinataire=self.admin, lu=False).count(), 0)
        self.assertEqual(Notification.objects.filter(destinataire=self.magasinier, lu=False).count(), 1)


class AbonnementsPushApiTests(NotifBase):
    ABONNEMENT = {
        "endpoint": "https://push.example/abc",
        "keys": {"p256dh": "cle-publique", "auth": "secret"},
        "user_agent": "Firefox",
    }

    def test_upsert_par_endpoint(self):
        self.client.force_authenticate(user=self.admin)
        r1 = self.client.post("/api/v1/notifications/abonnements/", self.ABONNEMENT, format="json")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        modifie = {**self.ABONNEMENT, "keys": {"p256dh": "nouvelle", "auth": "secret"}}
        r2 = self.client.post("/api/v1/notifications/abonnements/", modifie, format="json")
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(PushSubscription.objects.filter(endpoint=self.ABONNEMENT["endpoint"]).count(), 1)
        self.assertEqual(PushSubscription.objects.get(endpoint=self.ABONNEMENT["endpoint"]).p256dh, "nouvelle")

    def test_suppression_scopee(self):
        self.client.force_authenticate(user=self.admin)
        self.client.post("/api/v1/notifications/abonnements/", self.ABONNEMENT, format="json")
        # Le magasinier ne peut pas supprimer l'abonnement de l'admin.
        self.client.force_authenticate(user=self.magasinier)
        self.client.delete(f"/api/v1/notifications/abonnements/?endpoint={self.ABONNEMENT['endpoint']}")
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.client.force_authenticate(user=self.admin)
        r = self.client.delete(f"/api/v1/notifications/abonnements/?endpoint={self.ABONNEMENT['endpoint']}")
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(PushSubscription.objects.count(), 0)

    @override_settings(VAPID_PUBLIC_KEY="cle-publique-vapid")
    def test_cle_vapid_publique(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.get("/api/v1/notifications/cle-vapid-publique/")
        self.assertEqual(r.data, {"cle": "cle-publique-vapid"})


@override_settings(VAPID_PRIVATE_KEY="cle-privee", VAPID_CLAIM_EMAIL="mailto:test@example.com")
class EnvoiWebPushTests(NotifBase):
    def _abonner(self, utilisateur, endpoint="https://push.example/x"):
        return PushSubscription.objects.create(
            utilisateur=utilisateur, endpoint=endpoint, p256dh="p", auth="a",
        )

    @patch("apps.notifications.services.webpush")
    def test_webpush_appele_avec_les_bons_arguments(self, mock_webpush):
        self._abonner(self.admin)
        self._unite("F1")
        self._valider_sortie_avec(["F1"])
        self.assertTrue(mock_webpush.called)
        _, kwargs = mock_webpush.call_args
        self.assertEqual(kwargs["subscription_info"]["endpoint"], "https://push.example/x")
        self.assertEqual(kwargs["subscription_info"]["keys"], {"p256dh": "p", "auth": "a"})
        self.assertEqual(kwargs["vapid_private_key"], "cle-privee")
        self.assertEqual(kwargs["vapid_claims"], {"sub": "mailto:test@example.com"})
        self.assertIn("titre", kwargs["data"])

    @patch("apps.notifications.services.webpush")
    def test_abonnement_mort_supprime_sur_410_sans_casser_la_validation(self, mock_webpush):
        mock_webpush.side_effect = WebPushException("gone", response=SimpleNamespace(status_code=410))
        self._abonner(self.admin)
        self._unite("F1")
        self._valider_sortie_avec(["F1"])  # ne lève pas
        self.assertEqual(PushSubscription.objects.count(), 0)
        self.assertEqual(Notification.objects.filter(type=Notification.Type.MOUVEMENT_SORTIE).count(), 3)

    @patch("apps.notifications.services.webpush")
    def test_exception_push_ninterrompt_pas_la_validation(self, mock_webpush):
        mock_webpush.side_effect = RuntimeError("réseau")
        self._abonner(self.admin)
        self._unite("F1")
        self._valider_sortie_avec(["F1"])
        self.assertEqual(Notification.objects.filter(type=Notification.Type.MOUVEMENT_SORTIE).count(), 3)

    @override_settings(VAPID_PRIVATE_KEY="")
    @patch("apps.notifications.services.webpush")
    def test_sans_cle_vapid_pas_d_envoi(self, mock_webpush):
        self._abonner(self.admin)
        self._unite("F1")
        self._valider_sortie_avec(["F1"])
        mock_webpush.assert_not_called()
        self.assertEqual(Notification.objects.filter(type=Notification.Type.MOUVEMENT_SORTIE).count(), 3)
