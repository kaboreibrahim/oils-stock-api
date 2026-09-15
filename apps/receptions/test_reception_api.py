"""
=============================================================================
 apps/receptions/test_reception_api.py
 Flux : brouillon -> ajout de lignes (unité/plage) -> validation -> annulation,
 permissions par rôle (reprise réservée à l'admin), doublons, écriture des
 mouvements de stock, création de fournisseur à la volée en reprise.
=============================================================================
"""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework import status
from rest_framework.test import APITestCase

from apps.fournisseurs.models import Fournisseur
from apps.stock.models import MouvementStock, StatutStock, TypeArticle, TypeMouvement, UniteStock

from .models import LigneReception, Reception, StatutReception
from .repositories import ReceptionRepository

User = get_user_model()


class ReceptionApiTestsBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="test_admin", password="x", role=User.Role.ADMIN)
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")

    def _connecte(self, user):
        self.client.force_authenticate(user=user)

    def _creer_saisie(self, user=None, **overrides):
        self._connecte(user or self.magasinier)
        payload = {"nature": "SAISIE", "fournisseur": str(self.dhl.pk), "date_reception": "2026-09-10"}
        payload.update(overrides)
        response = self.client.post("/api/v1/receptions/", payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data


class ReceptionCreationTests(ReceptionApiTestsBase):
    def test_lecture_ouverte_a_tous_les_roles(self):
        for user in (self.admin, self.magasinier, self.lecteur):
            self._connecte(user)
            response = self.client.get("/api/v1/receptions/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)

    def test_creation_saisie_refusee_a_lecture_seule(self):
        self._connecte(self.lecteur)
        response = self.client.post(
            "/api/v1/receptions/", {"nature": "SAISIE", "fournisseur": str(self.dhl.pk), "date_reception": "2026-09-10"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creation_saisie_genere_une_reference_et_un_brouillon(self):
        data = self._creer_saisie()
        self.assertTrue(data["reference"].startswith("REC-"))
        self.assertEqual(data["statut"], StatutReception.BROUILLON)
        self.assertEqual(data["nb_lignes"], 0)

    def test_creation_saisie_sans_fournisseur_est_refusee(self):
        self._connecte(self.magasinier)
        response = self.client.post("/api/v1/receptions/", {"nature": "SAISIE", "date_reception": "2026-09-10"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_creation_reprise_refusee_au_magasinier(self):
        self._connecte(self.magasinier)
        response = self.client.post("/api/v1/receptions/", {"nature": "REPRISE", "date_reception": "2026-09-10"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creation_reprise_autorisee_a_l_admin(self):
        self._connecte(self.admin)
        response = self.client.post("/api/v1/receptions/", {"nature": "REPRISE", "date_reception": "2026-09-10"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNone(response.data["fournisseur"])

    def test_creation_retente_sur_collision_de_reference(self):
        """Miroir de apps.sorties.test_sortie_api — simule la course décrite
        dans _generer_reference() (bascule d'année, deux créations concurrentes) :
        le premier INSERT lève IntegrityError, le retry doit réussir."""
        original_create = ReceptionRepository.create
        appels = {"n": 0}

        def create_avec_collision_au_premier_appel(**data):
            appels["n"] += 1
            if appels["n"] == 1:
                raise IntegrityError("collision de référence simulée")
            return original_create(**data)

        with patch(
            "apps.receptions.repositories.ReceptionRepository.create",
            side_effect=create_avec_collision_au_premier_appel,
        ):
            resultat = self._creer_saisie()
        self.assertIn("reference", resultat)
        self.assertEqual(appels["n"], 2)


class ReceptionLigneSaisieTests(ReceptionApiTestsBase):
    def setUp(self):
        super().setUp()
        self.reception_id = self._creer_saisie()["id"]

    def test_ajout_ligne(self):
        response = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "008700", "type_article": "HEATING_PAD"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["statut_ligne"], "OK")
        self.assertEqual(response.data["source"], "MANUEL")

    def test_ajout_ligne_deja_en_stock_est_doublon(self):
        UniteStock.objects.create(
            numero_serie="008700", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        response = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "008700", "type_article": "HEATING_PAD"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["statut_ligne"], "DOUBLON")

    def test_ajout_ligne_deja_dans_la_reception_est_doublon(self):
        self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "008700", "type_article": "HEATING_PAD"},
        )
        response = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "008700", "type_article": "HEATING_PAD"},
        )
        self.assertEqual(response.data["statut_ligne"], "DOUBLON")

    def test_retrait_ligne(self):
        ligne = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "008700", "type_article": "HEATING_PAD"},
        ).data
        response = self.client.delete(f"/api/v1/receptions/{self.reception_id}/lignes/{ligne['id']}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(LigneReception.objects.filter(reception_id=self.reception_id).count(), 0)

    def test_generation_de_plage(self):
        response = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/plage/",
            {"prefixe": "24E3231260424A", "debut": 1, "fin": 5, "largeur": 3, "type_article": "FLEXITANK"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(len(response.data), 5)
        numeros = sorted(l["numero_serie"] for l in response.data)
        self.assertEqual(numeros, [f"24E3231260424A{i:03d}" for i in range(1, 6)])

    def test_generation_de_plage_bornes_inversees_est_refusee(self):
        response = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/plage/",
            {"prefixe": "X", "debut": 10, "fin": 1, "type_article": "FLEXITANK"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ReceptionValidationTests(ReceptionApiTestsBase):
    def setUp(self):
        super().setUp()
        self.reception_id = self._creer_saisie()["id"]

    def test_validation_sans_ligne_est_refusee(self):
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/valider/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validation_avec_doublon_est_refusee(self):
        UniteStock.objects.create(
            numero_serie="008700", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "008700", "type_article": "HEATING_PAD"},
        )
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/valider/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validation_cree_les_unites_et_ecrit_le_mouvement(self):
        self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "008700", "type_article": "HEATING_PAD"},
        )
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/valider/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["statut"], StatutReception.VALIDEE)

        unite = UniteStock.objects.get(numero_serie="008700", fournisseur=self.dhl)
        self.assertEqual(unite.statut, StatutStock.EN_STOCK)
        self.assertEqual(str(unite.reception_id), self.reception_id)
        self.assertEqual(unite.date_entree.isoformat(), "2026-09-10")

        mouvement = MouvementStock.objects.get(unite_stock=unite)
        self.assertEqual(mouvement.type_mouvement, TypeMouvement.ENTREE)
        self.assertEqual(str(mouvement.reception_id), self.reception_id)

    def test_modification_refusee_apres_validation(self):
        self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "008700", "type_article": "HEATING_PAD"},
        )
        self.client.post(f"/api/v1/receptions/{self.reception_id}/valider/")
        response = self.client.patch(f"/api/v1/receptions/{self.reception_id}/", {"reference_fournisseur": "X"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ReceptionAnnulationTests(ReceptionApiTestsBase):
    def setUp(self):
        super().setUp()
        self.reception_id = self._creer_saisie()["id"]
        self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "008700", "type_article": "HEATING_PAD"},
        )
        self.client.post(f"/api/v1/receptions/{self.reception_id}/valider/")
        # Annuler une réception déjà validée est réservé à l'admin (Jalon 6) —
        # création/validation ci-dessus restent magasinier (inchangé).
        self._connecte(self.admin)

    def test_annulation_reservee_a_admin(self):
        self._connecte(self.magasinier)
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/annuler/", {"motif": "Erreur de saisie"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_annulation_sans_motif_est_refusee(self):
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/annuler/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_annulation_retire_les_unites(self):
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/annuler/", {"motif": "Erreur de saisie"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["statut"], "ANNULEE")

        self.assertFalse(UniteStock.objects.filter(numero_serie="008700", fournisseur=self.dhl).exists())
        unite = UniteStock.all_objects.get(numero_serie="008700", fournisseur=self.dhl)
        self.assertTrue(unite.is_deleted)
        self.assertTrue(
            MouvementStock.objects.filter(unite_stock=unite, type_mouvement=TypeMouvement.ANNULATION_ENTREE).exists()
        )

    def test_annulation_refusee_si_unite_deja_sortie(self):
        unite = UniteStock.objects.get(numero_serie="008700", fournisseur=self.dhl)
        unite.statut = StatutStock.SORTIE
        unite.save(update_fields=["statut"])
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/annuler/", {"motif": "Erreur"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ReceptionRepriseTests(ReceptionApiTestsBase):
    def setUp(self):
        super().setUp()
        self._connecte(self.admin)
        self.reception_id = self.client.post(
            "/api/v1/receptions/", {"nature": "REPRISE", "date_reception": "2026-01-01"},
        ).data["id"]

    def test_ajout_ligne_reprise_avec_fournisseur_existant(self):
        response = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "0309260303099", "type_article": "HEATING_PAD", "fournisseur": str(self.dhl.pk)},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["source"], "REPRISE")

    def test_ajout_ligne_reprise_cree_le_fournisseur_a_la_volee(self):
        self.assertFalse(Fournisseur.objects.filter(code="LAF").exists())
        response = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "0309260303099", "type_article": "HEATING_PAD", "fournisseur_code": "laf"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(Fournisseur.objects.filter(code="LAF").exists())

    def test_ajout_ligne_reprise_sans_fournisseur_est_refuse(self):
        response = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "0309260303099", "type_article": "HEATING_PAD"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validation_reprise_commente_le_mouvement(self):
        self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "0309260303099", "type_article": "HEATING_PAD", "fournisseur": str(self.dhl.pk)},
        )
        self.client.post(f"/api/v1/receptions/{self.reception_id}/valider/")
        unite = UniteStock.objects.get(numero_serie="0309260303099")
        mouvement = MouvementStock.objects.get(unite_stock=unite)
        self.assertEqual(mouvement.commentaire, "Reprise de l'ancien système")
        self.assertEqual(unite.date_entree.isoformat(), "2026-01-01")


class ReceptionSuppressionEtFiltresTests(ReceptionApiTestsBase):
    def test_suppression_brouillon_est_logique(self):
        data = self._creer_saisie()
        response = self.client.delete(f"/api/v1/receptions/{data['id']}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Reception.objects.filter(pk=data["id"]).exists())
        self.assertTrue(Reception.all_objects.filter(pk=data["id"]).exists())

    def test_filtre_par_nature_et_statut(self):
        self._creer_saisie()
        self._connecte(self.admin)
        self.client.post("/api/v1/receptions/", {"nature": "REPRISE", "date_reception": "2026-09-10"})
        response = self.client.get("/api/v1/receptions/?nature=SAISIE")
        self.assertEqual(response.data["count"], 1)
        response = self.client.get("/api/v1/receptions/?statut=BROUILLON")
        self.assertEqual(response.data["count"], 2)

    def test_export_csv_ouvert_a_tous_les_roles(self):
        self._creer_saisie(reference_fournisseur="BL-12345")
        for user in (self.admin, self.magasinier, self.lecteur):
            self._connecte(user)
            response = self.client.get("/api/v1/receptions/export/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)
            self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
            contenu = response.content.decode("utf-8-sig")
            self.assertIn("Référence", contenu)
            self.assertIn("BL-12345", contenu)
