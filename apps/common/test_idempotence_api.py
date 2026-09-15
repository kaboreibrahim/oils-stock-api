"""
=============================================================================
 apps/common/test_idempotence_api.py
 Rejeu idempotent (en-tête Idempotency-Key) testé à travers un vrai endpoint
 (Sortie create) — apps.common lui-même n'a pas de route.
=============================================================================
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.clients.models import Client
from apps.sorties.models import Sortie

User = get_user_model()


class IdempotenceApiTests(APITestCase):
    def setUp(self):
        self.magasinier = User.objects.create_user(username="test_idem", password="x", role=User.Role.MAGASINIER)
        self.client_obj = Client.objects.create(code="IDEM1", nom="Client Idempotence")
        self.client.force_authenticate(user=self.magasinier)
        self.payload = {
            "client": str(self.client_obj.pk), "projet": "Projet idempotence",
            "trd": "TRD-IDEM", "date_sortie": "2026-09-15",
        }

    def test_meme_cle_idempotence_ne_cree_qu_une_sortie(self):
        r1 = self.client.post("/api/v1/sorties/", self.payload, HTTP_IDEMPOTENCY_KEY="cle-abc-123")
        r2 = self.client.post("/api/v1/sorties/", self.payload, HTTP_IDEMPOTENCY_KEY="cle-abc-123")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED, r1.data)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED, r2.data)
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(Sortie.objects.count(), 1)

    def test_sans_cle_deux_appels_creent_deux_sorties(self):
        # Non-régression : la clé est optionnelle, comportement actuel inchangé.
        r1 = self.client.post("/api/v1/sorties/", self.payload)
        r2 = self.client.post("/api/v1/sorties/", self.payload)
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Sortie.objects.count(), 2)

    def test_meme_cle_sur_un_chemin_different_est_rejetee(self):
        r1 = self.client.post("/api/v1/sorties/", self.payload, HTTP_IDEMPOTENCY_KEY="cle-partagee")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        r2 = self.client.post(
            "/api/v1/clients/", {"code": "AUTRECODE", "nom": "Autre client"}, HTTP_IDEMPOTENCY_KEY="cle-partagee",
        )
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cle_scindee_par_utilisateur(self):
        # Deux utilisateurs différents peuvent réutiliser la même valeur de
        # clé sans collision (contrainte d'unicité = (utilisateur, cle)).
        autre = User.objects.create_user(username="test_idem2", password="x", role=User.Role.MAGASINIER)
        r1 = self.client.post("/api/v1/sorties/", self.payload, HTTP_IDEMPOTENCY_KEY="cle-commune")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(user=autre)
        r2 = self.client.post("/api/v1/sorties/", self.payload, HTTP_IDEMPOTENCY_KEY="cle-commune")
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(Sortie.objects.count(), 2)

    def test_rejeu_via_action_imbriquee_lignes(self):
        sortie_id = self.client.post("/api/v1/sorties/", self.payload).data["id"]
        from apps.fournisseurs.models import Fournisseur
        from apps.stock.models import TypeArticle, UniteStock
        from datetime import date

        fournisseur = Fournisseur.objects.create(code="IDEMF", nom="Fournisseur Idempotence")
        UniteStock.objects.create(
            numero_serie="IDEM-UNIT-1", type_article=TypeArticle.HEATING_PAD,
            fournisseur=fournisseur, date_entree=date.today(),
        )
        r1 = self.client.post(
            f"/api/v1/sorties/{sortie_id}/lignes/", {"numero_serie": "IDEM-UNIT-1"},
            HTTP_IDEMPOTENCY_KEY="cle-ligne-1",
        )
        r2 = self.client.post(
            f"/api/v1/sorties/{sortie_id}/lignes/", {"numero_serie": "IDEM-UNIT-1"},
            HTTP_IDEMPOTENCY_KEY="cle-ligne-1",
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED, r1.data)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED, r2.data)
        self.assertEqual(r1.data["id"], r2.data["id"])
        # Une seule ligne créée malgré les deux POST — pas de doublon d'unité sortie.
        lignes = self.client.get(f"/api/v1/sorties/{sortie_id}/lignes/").data
        self.assertEqual(len(lignes), 1)
