"""
=============================================================================
 apps/sorties/test_sortie_api.py
 Flux : brouillon -> ajout de lignes -> validation -> annulation, permissions
 par rôle, écriture des mouvements de stock, disponibilité du bon de sortie.
=============================================================================
"""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework import status
from rest_framework.test import APITestCase

from apps.clients.models import Client
from apps.fournisseurs.models import Fournisseur
from apps.stock.models import MouvementStock, StatutStock, TypeArticle, TypeMouvement, UniteStock

from .models import LigneSortie, Sortie, StatutSortie
from .repositories import SortieRepository

User = get_user_model()


class SortieApiTestsBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="test_admin", password="x", role=User.Role.ADMIN)
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")
        self.laf = Fournisseur.objects.create(code="LAF", nom="LAF")
        self.client_obj = Client.objects.create(code="SOFIT", nom="Société Ivoirienne des Textiles")
        self.unite = UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )

    def _connecte(self, user):
        self.client.force_authenticate(user=user)

    def _creer_sortie(self, user=None):
        self._connecte(user or self.magasinier)
        response = self.client.post(
            "/api/v1/sorties/",
            {
                "client": str(self.client_obj.pk), "projet": "Rénovation dépôt Nord",
                "trd": "TRD-001", "date_sortie": "2026-09-10",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data


class SortieCreationTests(SortieApiTestsBase):
    def test_lecture_ouverte_a_tous_les_roles(self):
        for user in (self.admin, self.magasinier, self.lecteur):
            self._connecte(user)
            response = self.client.get("/api/v1/sorties/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)

    def test_creation_refusee_a_lecture_seule(self):
        self._connecte(self.lecteur)
        response = self.client.post(
            "/api/v1/sorties/",
            {"client": str(self.client_obj.pk), "projet": "X", "trd": "TRD-1", "date_sortie": "2026-09-10"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creation_genere_une_reference_et_un_brouillon(self):
        data = self._creer_sortie()
        self.assertTrue(data["reference"].startswith("SOR-"))
        self.assertEqual(data["statut"], StatutSortie.BROUILLON)
        self.assertEqual(data["nb_unites"], 0)

    def test_references_se_suivent(self):
        premiere = self._creer_sortie()
        deuxieme = self._creer_sortie()
        num1 = int(premiere["reference"].rsplit("-", 1)[-1])
        num2 = int(deuxieme["reference"].rsplit("-", 1)[-1])
        self.assertEqual(num2, num1 + 1)

    def test_creation_retente_sur_collision_de_reference(self):
        """Simule la course décrite dans _generer_reference() (bascule d'année,
        deux créations concurrentes) : le premier INSERT lève IntegrityError,
        le retry doit réussir sans remonter d'erreur à l'appelant."""
        original_create = SortieRepository.create
        appels = {"n": 0}

        def create_avec_collision_au_premier_appel(**data):
            appels["n"] += 1
            if appels["n"] == 1:
                raise IntegrityError("collision de référence simulée")
            return original_create(**data)

        with patch(
            "apps.sorties.repositories.SortieRepository.create",
            side_effect=create_avec_collision_au_premier_appel,
        ):
            resultat = self._creer_sortie()
        self.assertIn("reference", resultat)
        self.assertEqual(appels["n"], 2)


class SortieLigneTests(SortieApiTestsBase):
    def setUp(self):
        super().setUp()
        self.sortie_data = self._creer_sortie()
        self.sortie_id = self.sortie_data["id"]

    def test_ajout_ligne_unite_en_stock(self):
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["numero_serie"], "008647")
        self.assertEqual(LigneSortie.objects.filter(sortie_id=self.sortie_id).count(), 1)

    def test_ajout_ligne_unite_inexistante_est_refuse(self):
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "INCONNU"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ajout_ligne_unite_deja_sortie_est_refuse(self):
        self.unite.statut = StatutStock.SORTIE
        self.unite.save(update_fields=["statut"])
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ajout_ligne_numero_ambigu_entre_fournisseurs_est_refuse_sans_precision(self):
        UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.laf, date_entree=date.today(),
        )
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            f"/api/v1/sorties/{self.sortie_id}/lignes/",
            {"numero_serie": "008647", "fournisseur": str(self.dhl.pk)},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_retrait_ligne(self):
        ligne = self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"}).data
        response = self.client.delete(f"/api/v1/sorties/{self.sortie_id}/lignes/{ligne['id']}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(LigneSortie.objects.filter(sortie_id=self.sortie_id).count(), 0)

    def test_ajout_ligne_refuse_a_lecture_seule(self):
        self._connecte(self.lecteur)
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SortieValidationTests(SortieApiTestsBase):
    def setUp(self):
        super().setUp()
        self.sortie_data = self._creer_sortie()
        self.sortie_id = self.sortie_data["id"]

    def test_validation_sans_ligne_est_refusee(self):
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/valider/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validation_fait_sortir_les_unites_et_ecrit_le_mouvement(self):
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/valider/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["statut"], StatutSortie.VALIDEE)

        self.unite.refresh_from_db()
        self.assertEqual(self.unite.statut, StatutStock.SORTIE)
        self.assertEqual(str(self.unite.sortie_id), self.sortie_id)
        self.assertEqual(self.unite.date_sortie.isoformat(), "2026-09-10")

        mouvement = MouvementStock.objects.get(unite_stock=self.unite)
        self.assertEqual(mouvement.type_mouvement, TypeMouvement.SORTIE)
        self.assertEqual(str(mouvement.sortie_id), self.sortie_id)

    def test_bon_de_sortie_indisponible_avant_validation(self):
        response = self.client.get(f"/api/v1/sorties/{self.sortie_id}/bon-de-sortie.pdf/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bon_de_sortie_disponible_apres_validation(self):
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/valider/")
        response = self.client.get(f"/api/v1/sorties/{self.sortie_id}/bon-de-sortie.pdf/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        contenu = b"".join(response.streaming_content)
        self.assertTrue(contenu.startswith(b"%PDF"))
        # Logo + bloc de signature en plus du tableau d'origine : un bon
        # minimal sans ces ajouts ferait quelques Ko, pas plusieurs dizaines.
        self.assertGreater(len(contenu), 20_000)

    def test_bon_de_sortie_contient_la_repartition_par_type(self):
        """Le tableau récapitulatif (Flexitank/Heating pad, en plus du détail
        unité par unité) doit refléter les quantités réellement sorties."""
        import io

        import pdfplumber

        flexitank = UniteStock.objects.create(
            numero_serie="24E3231260424A001", type_article=TypeArticle.FLEXITANK,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": flexitank.numero_serie})
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/valider/")

        response = self.client.get(f"/api/v1/sorties/{self.sortie_id}/bon-de-sortie.pdf/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        contenu = b"".join(response.streaming_content)

        with pdfplumber.open(io.BytesIO(contenu)) as pdf:
            texte = "\n".join(page.extract_text() or "" for page in pdf.pages)

        self.assertIn("Répartition par type", texte)
        self.assertIn("Flexitank", texte)
        self.assertIn("Heating pad", texte)
        # Une occurrence de "1" par type sorti, "2" pour le total — vérifiées via
        # la présence de la ligne "Total 2" plutôt qu'un simple "in" sur "2" ou
        # "1" (trop souvent présents ailleurs dans le document : dates, etc.).
        self.assertRegex(texte, r"Total\s+2")

    def test_bon_de_sortie_ne_plante_pas_si_le_logo_est_absent(self):
        """Déploiement incomplet, fichier déplacé... — le bon doit rester
        généré (juste sans logo), jamais un 500."""
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/valider/")
        with patch("apps.sorties.pdf.LOGO_PATH", Path("/chemin/inexistant/logo.png")):
            response = self.client.get(f"/api/v1/sorties/{self.sortie_id}/bon-de-sortie.pdf/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_modification_refusee_apres_validation(self):
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/valider/")
        response = self.client.patch(f"/api/v1/sorties/{self.sortie_id}/", {"trd": "TRD-999"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SortieAnnulationTests(SortieApiTestsBase):
    def setUp(self):
        super().setUp()
        self.sortie_data = self._creer_sortie()
        self.sortie_id = self.sortie_data["id"]
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/lignes/", {"numero_serie": "008647"})
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/valider/")
        # Annuler une sortie déjà validée est réservé à l'admin (Jalon 6) —
        # la création/validation ci-dessus reste magasinier (inchangé),
        # seule l'annulation elle-même bascule sur l'admin pour ces tests.
        self._connecte(self.admin)

    def test_annulation_reservee_a_admin(self):
        self._connecte(self.magasinier)
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/annuler/", {"motif": "Erreur de saisie"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_annulation_sans_motif_est_refusee(self):
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/annuler/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_annulation_remet_les_unites_en_stock(self):
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/annuler/", {"motif": "Erreur de saisie"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["statut"], StatutSortie.ANNULEE)

        self.unite.refresh_from_db()
        self.assertEqual(self.unite.statut, StatutStock.EN_STOCK)
        self.assertIsNone(self.unite.sortie_id)

        self.assertTrue(
            MouvementStock.objects.filter(
                unite_stock=self.unite, type_mouvement=TypeMouvement.ANNULATION_SORTIE,
            ).exists()
        )

    def test_annulation_deja_annulee_est_refusee(self):
        self.client.post(f"/api/v1/sorties/{self.sortie_id}/annuler/", {"motif": "Erreur de saisie"})
        response = self.client.post(f"/api/v1/sorties/{self.sortie_id}/annuler/", {"motif": "Encore"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SortieSuppressionEtFiltresTests(SortieApiTestsBase):
    def test_suppression_brouillon_est_logique(self):
        data = self._creer_sortie()
        response = self.client.delete(f"/api/v1/sorties/{data['id']}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Sortie.objects.filter(pk=data["id"]).exists())
        self.assertTrue(Sortie.all_objects.filter(pk=data["id"]).exists())

    def test_filtre_par_client_et_statut(self):
        autre_client = Client.objects.create(code="AUTRE", nom="Autre client")
        self._creer_sortie()
        self._connecte(self.magasinier)
        self.client.post(
            "/api/v1/sorties/",
            {"client": str(autre_client.pk), "projet": "Y", "trd": "TRD-2", "date_sortie": "2026-09-11"},
        )
        response = self.client.get(f"/api/v1/sorties/?client={self.client_obj.pk}")
        self.assertEqual(response.data["count"], 1)
        response = self.client.get("/api/v1/sorties/?statut=BROUILLON")
        self.assertEqual(response.data["count"], 2)

    def test_projets_autocomplete(self):
        self._creer_sortie()
        self._connecte(self.lecteur)
        response = self.client.get("/api/v1/projets/?q=nord")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Rénovation dépôt Nord", response.data)

    def test_export_csv_ouvert_a_tous_les_roles(self):
        self._creer_sortie()
        for user in (self.admin, self.magasinier, self.lecteur):
            self._connecte(user)
            response = self.client.get("/api/v1/sorties/export/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)
            self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
            contenu = response.content.decode("utf-8-sig")
            self.assertIn("Référence", contenu)
            self.assertIn("Rénovation dépôt Nord", contenu)

    def test_export_csv_respecte_les_filtres(self):
        autre_client = Client.objects.create(code="AUTRE2", nom="Encore un autre")
        self._creer_sortie()
        self._connecte(self.magasinier)
        self.client.post(
            "/api/v1/sorties/",
            {"client": str(autre_client.pk), "projet": "Z", "trd": "TRD-3", "date_sortie": "2026-09-12"},
        )
        response = self.client.get(f"/api/v1/sorties/export/?client={self.client_obj.pk}")
        contenu = response.content.decode("utf-8-sig")
        self.assertIn("Rénovation dépôt Nord", contenu)
        self.assertNotIn("TRD-3", contenu)
