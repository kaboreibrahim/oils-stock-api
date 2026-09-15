"""
=============================================================================
 apps/clients/test_client_api.py
 Flux : lecture ouverte à tous les rôles, écriture pour magasinier + admin,
 unicité de code, suppression logique.
=============================================================================
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Client

User = get_user_model()


class ClientApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="test_admin", password="x", role=User.Role.ADMIN)
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)
        self.client_obj = Client.objects.create(code="SOFIT", nom="Société Ivoirienne des Textiles")

    def _connecte(self, user):
        self.client.force_authenticate(user=user)

    def test_lecture_ouverte_a_tous_les_roles(self):
        for user in (self.admin, self.magasinier, self.lecteur):
            self._connecte(user)
            response = self.client.get("/api/v1/clients/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)

    def test_creation_refusee_a_lecture_seule(self):
        self._connecte(self.lecteur)
        response = self.client.post("/api/v1/clients/", {"code": "NEWC", "nom": "Nouveau client"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creation_autorisee_pour_magasinier_et_admin(self):
        for i, user in enumerate((self.magasinier, self.admin)):
            self._connecte(user)
            response = self.client.post("/api/v1/clients/", {"code": f"NEWC{i}", "nom": "Nouveau client"})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, user.username)

    def test_code_deja_utilise_est_rejete(self):
        self._connecte(self.magasinier)
        response = self.client.post("/api/v1/clients/", {"code": "sofit", "nom": "Doublon"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suppression_est_logique(self):
        self._connecte(self.admin)
        response = self.client.delete(f"/api/v1/clients/{self.client_obj.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Client.objects.filter(pk=self.client_obj.pk).exists())
        self.assertTrue(Client.all_objects.filter(pk=self.client_obj.pk).exists())

    def test_code_dun_client_supprime_reste_bloque_proprement(self):
        """Bug réel rencontré en testant l'écran de détail (Jalon 5+) : `code`
        est unique au niveau base sur TOUTES les lignes (supprimées incluses),
        mais l'ancienne vérification ne regardait que les lignes actives
        (`objects`) — recréer avec le même code après une suppression logique
        levait une IntegrityError brute (500) au lieu d'un 400 propre."""
        self._connecte(self.admin)
        self.client.delete(f"/api/v1/clients/{self.client_obj.pk}/")
        response = self.client.post("/api/v1/clients/", {"code": "SOFIT", "nom": "Rebond"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_meme_cle_idempotence_ne_cree_qu_un_client(self):
        """Phase 2 PWA — écriture hors-ligne : un rejeu (même Idempotency-Key)
        après une coupure réseau ne doit jamais créer un doublon."""
        self._connecte(self.magasinier)
        payload = {"code": "IDEMC", "nom": "Client idempotent"}
        r1 = self.client.post("/api/v1/clients/", payload, HTTP_IDEMPOTENCY_KEY="cle-client-1")
        r2 = self.client.post("/api/v1/clients/", payload, HTTP_IDEMPOTENCY_KEY="cle-client-1")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED, r1.data)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED, r2.data)
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(Client.objects.filter(code="IDEMC").count(), 1)

    def test_meme_cle_idempotence_sur_modification_ne_reapplique_pas(self):
        self._connecte(self.magasinier)
        payload = {"pays": "Sénégal"}
        r1 = self.client.patch(f"/api/v1/clients/{self.client_obj.pk}/", payload, HTTP_IDEMPOTENCY_KEY="cle-patch-1")
        r2 = self.client.patch(f"/api/v1/clients/{self.client_obj.pk}/", payload, HTTP_IDEMPOTENCY_KEY="cle-patch-1")
        self.assertEqual(r1.status_code, status.HTTP_200_OK, r1.data)
        self.assertEqual(r2.status_code, status.HTTP_200_OK, r2.data)
        self.assertEqual(r1.data, r2.data)
