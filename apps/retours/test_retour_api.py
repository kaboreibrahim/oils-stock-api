"""
=============================================================================
 apps/retours/test_retour_api.py
 Flux : une unité SORTIE revient EN_STOCK, la sortie d'origine reste VALIDEE,
 le mouvement RETOUR garde le lien vers elle.
=============================================================================
"""

from datetime import date

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.clients.models import Client
from apps.fournisseurs.models import Fournisseur
from apps.sorties.models import StatutSortie
from apps.stock.models import MouvementStock, StatutStock, TypeArticle, TypeMouvement, UniteStock

User = get_user_model()


class RetourApiTests(APITestCase):
    def setUp(self):
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")
        self.client_obj = Client.objects.create(code="SOFIT", nom="Société Ivoirienne des Textiles")
        self.unite = UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        self.client.force_authenticate(user=self.magasinier)
        sortie_data = self.client.post(
            "/api/v1/sorties/",
            {
                "client": str(self.client_obj.pk), "projet": "Rénovation dépôt Nord",
                "trd": "TRD-001", "date_sortie": "2026-09-10",
            },
        ).data
        self.sortie_id = sortie_data["id"]
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/valider/")

    def test_retour_remet_l_unite_en_stock_sans_toucher_la_sortie(self):
        response = self.client.post(
            "/api/v1/retours/",
            {
                "unites": [{"numero_serie": "008647"}],
                "date_retour": "2026-09-12",
                "motif": "Renvoi client — projet annulé",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        self.unite.refresh_from_db()
        self.assertEqual(self.unite.statut, StatutStock.EN_STOCK)
        self.assertIsNone(self.unite.sortie_id)

        mouvement = MouvementStock.objects.get(unite_stock=self.unite, type_mouvement=TypeMouvement.RETOUR)
        self.assertEqual(str(mouvement.sortie_id), self.sortie_id)

        from apps.sorties.models import Sortie
        sortie = Sortie.objects.get(pk=self.sortie_id)
        self.assertEqual(sortie.statut, StatutSortie.VALIDEE)

    def test_retour_unite_en_stock_est_refuse(self):
        autre = UniteStock.objects.create(
            numero_serie="999999", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        response = self.client.post(
            "/api/v1/retours/",
            {"unites": [{"numero_serie": "999999"}], "date_retour": "2026-09-12", "motif": "X"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        autre.refresh_from_db()
        self.assertEqual(autre.statut, StatutStock.EN_STOCK)

    def test_retour_sans_motif_est_refuse(self):
        response = self.client.post(
            "/api/v1/retours/",
            {"unites": [{"numero_serie": "008647"}], "date_retour": "2026-09-12", "motif": ""},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retour_refuse_a_lecture_seule(self):
        self.client.force_authenticate(user=self.lecteur)
        response = self.client.post(
            "/api/v1/retours/",
            {"unites": [{"numero_serie": "008647"}], "date_retour": "2026-09-12", "motif": "X"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
