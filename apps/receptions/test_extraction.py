"""
=============================================================================
 apps/receptions/test_extraction.py
 Flux : profil d'extraction (fournisseurs), création d'un arrivage avec PDF,
 (re)lancement de l'extraction — profil connu vs détection générique,
 doublons, détection de plage, bout en bout jusqu'à la validation.

 Les PDF sont générés à la volée avec reportlab (déjà utilisé pour le bon de
 sortie) — pas de fichier fixture à maintenir, et ça exerce le vrai moteur
 pdfplumber plutôt qu'un mock.
=============================================================================
"""

import io
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
from rest_framework import status
from rest_framework.test import APITestCase

from apps.fournisseurs.models import Fournisseur
from apps.stock.models import MouvementStock, StatutStock, TypeArticle, TypeMouvement, UniteStock

from .models import LigneReception, Reception, SourceLigneReception, StatutLigneReception, StatutReception

User = get_user_model()


def pdf_grille(numeros: list[str], entete: str = "") -> SimpleUploadedFile:
    """Grille sans en-tête, 5 colonnes — comme le PDF Ebont réel (§05 du dossier de conception)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [Paragraph(entete or "Bordereau", styles["Normal"]), Spacer(1, 12)]
    lignes = [numeros[i : i + 5] for i in range(0, len(numeros), 5)]
    elements.append(Table(lignes))
    doc.build(elements)
    buffer.seek(0)
    return SimpleUploadedFile("arrivage.pdf", buffer.read(), content_type="application/pdf")


def pdf_tableau(numeros: list[str], entetes=("N° série", "Type")) -> SimpleUploadedFile:
    """Tableau avec en-têtes — comme les listes DHL/LAF (mode TABLEAU)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [Paragraph("Bordereau", styles["Normal"]), Spacer(1, 12)]
    lignes = [list(entetes)] + [[n, "X"] for n in numeros]
    elements.append(Table(lignes))
    doc.build(elements)
    buffer.seek(0)
    return SimpleUploadedFile("arrivage.pdf", buffer.read(), content_type="application/pdf")


EBONT_NUMEROS = [f"24E3231260424A{i:03d}" for i in range(1, 11)]  # 10 pour des tests rapides
DHL_NUMEROS = [f"{800000 + i:06d}" for i in range(1, 11)]


class ProfilExtractionApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="test_admin", password="x", role=User.Role.ADMIN)
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.ebont = Fournisseur.objects.create(code="EBONT", nom="Ebont")

    def _connecte(self, user):
        self.client.force_authenticate(user=user)

    def test_lecture_ouverte_a_tous(self):
        self._connecte(self.magasinier)
        response = self.client.get(f"/api/v1/fournisseurs/{self.ebont.pk}/profil-extraction/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["regex_numero_serie"], "")

    def test_ecriture_refusee_au_magasinier(self):
        self._connecte(self.magasinier)
        response = self.client.put(
            f"/api/v1/fournisseurs/{self.ebont.pk}/profil-extraction/",
            {"mode_extraction": "GRILLE", "regex_numero_serie": r"24E\d{10}A\d{3}", "type_article_defaut": "FLEXITANK"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_ecriture_autorisee_a_l_admin(self):
        self._connecte(self.admin)
        response = self.client.put(
            f"/api/v1/fournisseurs/{self.ebont.pk}/profil-extraction/",
            {"mode_extraction": "GRILLE", "regex_numero_serie": r"24E\d{10}A\d{3}", "type_article_defaut": "FLEXITANK"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.ebont.refresh_from_db()
        self.assertEqual(self.ebont.mode_extraction, "GRILLE")
        self.assertTrue(self.ebont.a_un_profil_extraction)


class ExtractionApiTestsBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="test_admin", password="x", role=User.Role.ADMIN)
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.ebont = Fournisseur.objects.create(
            code="EBONT", nom="Ebont", mode_extraction="GRILLE",
            regex_numero_serie=r"24E\d{10}A\d{3}", type_article_defaut=TypeArticle.FLEXITANK,
        )
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")  # pas de profil
        self.client.force_authenticate(user=self.magasinier)

    def _creer_arrivage(self, fournisseur, fichier):
        response = self.client.post(
            "/api/v1/receptions/",
            {"nature": "ARRIVAGE", "fournisseur": str(fournisseur.pk), "date_reception": "2026-09-10", "fichier": fichier},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data["id"]


class ReceptionArrivageCreationTests(ExtractionApiTestsBase):
    def test_arrivage_sans_fichier_est_refuse(self):
        response = self.client.post(
            "/api/v1/receptions/",
            {"nature": "ARRIVAGE", "fournisseur": str(self.ebont.pk), "date_reception": "2026-09-10"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_arrivage_avec_fichier_pdf_est_accepte(self):
        reception_id = self._creer_arrivage(self.ebont, pdf_grille(EBONT_NUMEROS))
        reception = Reception.objects.get(pk=reception_id)
        self.assertTrue(reception.fichier.name.endswith(".pdf"))

    def test_fichier_non_pdf_est_refuse(self):
        mauvais = SimpleUploadedFile("bordereau.txt", b"pas un pdf", content_type="text/plain")
        response = self.client.post(
            "/api/v1/receptions/",
            {"nature": "ARRIVAGE", "fournisseur": str(self.ebont.pk), "date_reception": "2026-09-10", "fichier": mauvais},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_telechargement_du_fichier_via_l_api(self):
        # Servi par l'API (authentifié), pas l'URL média brute — évite un
        # souci CORS quand le frontend n'est pas sur le même hôte (tunnel).
        reception_id = self._creer_arrivage(self.ebont, pdf_grille(EBONT_NUMEROS))
        response = self.client.get(f"/api/v1/receptions/{reception_id}/fichier/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")


class ExtractionAvecProfilTests(ExtractionApiTestsBase):
    def setUp(self):
        super().setUp()
        self.reception_id = self._creer_arrivage(self.ebont, pdf_grille(EBONT_NUMEROS, "Lot EBT260407 — 10 SETS"))

    def test_extraction_cree_les_lignes_avec_le_bon_profil(self):
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/extraire/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data["lignes"]), 10)
        self.assertFalse(response.data["generique"])
        for ligne in response.data["lignes"]:
            self.assertEqual(ligne["statut_ligne"], "OK")
            self.assertEqual(ligne["source"], "EXTRACTION")
            self.assertEqual(ligne["type_article"], "FLEXITANK")

        reception = Reception.objects.get(pk=self.reception_id)
        self.assertEqual(reception.quantite_annoncee, 10)  # « 10 SETS » détecté dans le texte

    def test_plage_detectee_dans_la_reponse(self):
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/extraire/")
        plage = response.data["plage_detectee"]
        self.assertIsNotNone(plage)
        self.assertEqual(plage["prefixe"], "24E3231260424A")
        self.assertEqual(plage["debut"], 1)
        self.assertEqual(plage["fin"], 10)
        self.assertTrue(plage["complet"])

    def test_doublon_detecte_parmi_les_lignes_extraites(self):
        UniteStock.objects.create(
            numero_serie=EBONT_NUMEROS[0], type_article=TypeArticle.FLEXITANK,
            fournisseur=self.ebont, date_entree=date.today(),
        )
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/extraire/")
        statuts = {l["numero_serie"]: l["statut_ligne"] for l in response.data["lignes"]}
        self.assertEqual(statuts[EBONT_NUMEROS[0]], "DOUBLON")
        self.assertEqual(statuts[EBONT_NUMEROS[1]], "OK")

    def test_reextraction_conserve_les_lignes_manuelles(self):
        self.client.post(f"/api/v1/receptions/{self.reception_id}/extraire/")
        self.client.post(
            f"/api/v1/receptions/{self.reception_id}/lignes/",
            {"numero_serie": "MANUEL-001", "type_article": "FLEXITANK"},
        )
        self.assertEqual(LigneReception.objects.filter(reception_id=self.reception_id).count(), 11)

        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/extraire/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Les 10 lignes EXTRACTION ont été remplacées (toujours 10, pas 20), la manuelle reste.
        lignes = LigneReception.objects.filter(reception_id=self.reception_id)
        self.assertEqual(lignes.count(), 11)
        self.assertTrue(lignes.filter(numero_serie="MANUEL-001", source=SourceLigneReception.MANUEL).exists())

    def test_extraction_refusee_hors_brouillon(self):
        self.client.post(f"/api/v1/receptions/{self.reception_id}/extraire/")
        # Ajoute une ligne manuelle valide en plus pour que la validation ne bloque pas sur un doublon,
        # puis valide — l'extraction doit ensuite être refusée (déjà VALIDEE).
        self.client.post(f"/api/v1/receptions/{self.reception_id}/valider/")
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/extraire/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_extraction_bout_en_bout_jusqu_a_la_validation(self):
        self.client.post(f"/api/v1/receptions/{self.reception_id}/extraire/")
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/valider/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["statut"], StatutReception.VALIDEE)

        self.assertEqual(UniteStock.objects.filter(fournisseur=self.ebont).count(), 10)
        premiere = UniteStock.objects.get(numero_serie=EBONT_NUMEROS[0], fournisseur=self.ebont)
        self.assertEqual(premiere.statut, StatutStock.EN_STOCK)
        mouvement = MouvementStock.objects.get(unite_stock=premiere)
        self.assertEqual(mouvement.type_mouvement, TypeMouvement.ENTREE)
        self.assertEqual(str(mouvement.reception_id), self.reception_id)


class ExtractionSansProfilTests(ExtractionApiTestsBase):
    def setUp(self):
        super().setUp()
        self.reception_id = self._creer_arrivage(self.dhl, pdf_tableau(DHL_NUMEROS))

    def test_extraction_sans_profil_est_generique_et_a_verifier(self):
        response = self.client.post(
            f"/api/v1/receptions/{self.reception_id}/extraire/", {"type_article": "HEATING_PAD"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["generique"])
        self.assertGreater(len(response.data["lignes"]), 0)
        for ligne in response.data["lignes"]:
            self.assertEqual(ligne["statut_ligne"], "A_VERIFIER")

    def test_extraction_sans_type_article_ni_defaut_est_refusee(self):
        response = self.client.post(f"/api/v1/receptions/{self.reception_id}/extraire/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
