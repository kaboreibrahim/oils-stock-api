"""
=============================================================================
 apps/stock/test_stock_api.py
 Flux : lecture des unités de stock, contrainte d'unicité (fournisseur,
 numero_serie) — deux fournisseurs peuvent partager un même numéro, un seul
 ne peut pas l'avoir en double —, résolution scan (lookup / OCR photo, Jalon 5).
=============================================================================
"""

import io
from datetime import date
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont
from rest_framework import status
from rest_framework.test import APITestCase

from apps.common.ocr import _resoudre_binaire_tesseract
from apps.fournisseurs.models import Fournisseur

from .models import MouvementStock, StatutStock, TypeArticle, TypeMouvement, UniteStock

TESSERACT_DISPONIBLE = _resoudre_binaire_tesseract() is not None

User = get_user_model()


def photo_avec_texte(lignes: list[str]) -> SimpleUploadedFile:
    """Photo de synthèse (comme si prise au téléphone) — un numéro par ligne,
    assez grand pour un OCR fiable."""
    image = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(image)
    police = ImageFont.load_default(size=32)
    y = 20
    for ligne in lignes:
        draw.text((20, y), ligne, fill="black", font=police)
        y += 45
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return SimpleUploadedFile("photo.png", buffer.read(), content_type="image/png")


class UniteStockApiTests(APITestCase):
    def setUp(self):
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")
        self.unite = UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )

    def test_lecture_ouverte_a_lecture_seule(self):
        self.client.force_authenticate(user=self.lecteur)
        response = self.client.get("/api/v1/unites/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_detail_unite(self):
        self.client.force_authenticate(user=self.lecteur)
        response = self.client.get(f"/api/v1/unites/{self.unite.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["numero_serie"], "008647")
        self.assertEqual(response.data["fournisseur_code"], "DHL")

    def test_filtre_par_statut(self):
        self.client.force_authenticate(user=self.lecteur)
        response = self.client.get("/api/v1/unites/?statut=SORTIE")
        self.assertEqual(response.data["count"], 0)


class UniteStockUniciteTests(TestCase):
    """Le numéro de série appartient au fournisseur (§02/§04 du dossier de conception)."""

    def setUp(self):
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")
        self.laf = Fournisseur.objects.create(code="LAF", nom="LAF")

    def test_meme_numero_chez_deux_fournisseurs_differents_est_autorise(self):
        UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.laf, date_entree=date.today(),
        )
        self.assertEqual(UniteStock.objects.filter(numero_serie="008647").count(), 2)

    def test_meme_numero_chez_le_meme_fournisseur_est_rejete(self):
        UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UniteStock.objects.create(
                    numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
                    fournisseur=self.dhl, date_entree=date.today(),
                )


class UniteStockLookupApiTests(APITestCase):
    """Résolution scan (§07 du dossier de conception) — code_interne ou
    numero_serie exact, liste vide/simple/multiple selon les cas."""

    def setUp(self):
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")
        self.laf = Fournisseur.objects.create(code="LAF", nom="LAF")
        self.client.force_authenticate(user=self.lecteur)

    def test_lookup_par_numero_serie_unique(self):
        UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        response = self.client.get("/api/v1/unites/lookup/?q=008647")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["numero_serie"], "008647")

    def test_lookup_par_code_interne(self):
        UniteStock.objects.create(
            numero_serie="008647", code_interne="QR-42", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        response = self.client.get("/api/v1/unites/lookup/?q=QR-42")
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["code_interne"], "QR-42")

    def test_lookup_ambigu_renvoie_plusieurs_unites(self):
        UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.laf, date_entree=date.today(),
        )
        response = self.client.get("/api/v1/unites/lookup/?q=008647")
        self.assertEqual(len(response.data), 2)

    def test_lookup_sans_resultat_renvoie_liste_vide(self):
        response = self.client.get("/api/v1/unites/lookup/?q=INCONNU")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])


class UniteStockScannerApiTests(APITestCase):
    """OCR d'une photo de scan mobile (Jalon 5)."""

    def setUp(self):
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")
        self.client.force_authenticate(user=self.magasinier)

    def test_scanner_sans_image_est_refuse(self):
        response = self.client.post("/api/v1/unites/scanner/", {}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_scanner_fichier_illisible_est_refuse(self):
        mauvais = SimpleUploadedFile("photo.png", b"pas une image", content_type="image/png")
        response = self.client.post("/api/v1/unites/scanner/", {"image": mauvais}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @skipUnless(TESSERACT_DISPONIBLE, "Tesseract non installé sur cette machine")
    def test_scanner_resout_une_unite_connue(self):
        UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        response = self.client.post(
            "/api/v1/unites/scanner/", {"image": photo_avec_texte(["008647"])}, format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(any(r["candidat"] == "008647" and r["unites"] for r in response.data))

    @skipUnless(TESSERACT_DISPONIBLE, "Tesseract non installé sur cette machine")
    def test_scanner_jeton_inconnu_renvoie_unites_vide(self):
        response = self.client.post(
            "/api/v1/unites/scanner/", {"image": photo_avec_texte(["XKPQZ9"])}, format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for resultat in response.data:
            if resultat["candidat"] == "XKPQZ9":
                self.assertEqual(resultat["unites"], [])


class ExportsCsvApiTests(APITestCase):
    """Exports CSV (Jalon 6, §09 — ouvert à tous les rôles)."""

    def setUp(self):
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")
        self.unite = UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        self.mouvement = MouvementStock.objects.create(
            unite_stock=self.unite, type_mouvement=TypeMouvement.ENTREE, date_mouvement=timezone.now(),
        )
        self.client.force_authenticate(user=self.lecteur)

    def test_export_unites_csv(self):
        response = self.client.get("/api/v1/unites/export/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])
        contenu = response.content.decode("utf-8-sig")
        self.assertIn("Numéro de série", contenu)
        self.assertIn("008647", contenu)
        self.assertIn("Heating pad", contenu)

    def test_export_unites_csv_respecte_les_filtres(self):
        UniteStock.objects.create(
            numero_serie="999999", type_article=TypeArticle.FLEXITANK,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        response = self.client.get("/api/v1/unites/export/?type_article=HEATING_PAD")
        contenu = response.content.decode("utf-8-sig")
        self.assertIn("008647", contenu)
        self.assertNotIn("999999", contenu)

    def test_export_mouvements_csv(self):
        response = self.client.get("/api/v1/mouvements/export/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        contenu = response.content.decode("utf-8-sig")
        self.assertIn("Numéro de série", contenu)
        self.assertIn("008647", contenu)
        self.assertIn("Entrée", contenu)


class MouvementFiltreParFournisseurApiTests(APITestCase):
    """Filtre `unite_stock__fournisseur` — dernières transactions d'un
    fournisseur (fiche fournisseur, Jalon 6+)."""

    def setUp(self):
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")
        self.laf = Fournisseur.objects.create(code="LAF", nom="LAF")
        unite_dhl = UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        unite_laf = UniteStock.objects.create(
            numero_serie="0309260303099", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.laf, date_entree=date.today(),
        )
        MouvementStock.objects.create(unite_stock=unite_dhl, type_mouvement=TypeMouvement.ENTREE, date_mouvement=timezone.now())
        MouvementStock.objects.create(unite_stock=unite_laf, type_mouvement=TypeMouvement.ENTREE, date_mouvement=timezone.now())
        self.client.force_authenticate(user=self.lecteur)

    def test_filtre_ne_renvoie_que_les_mouvements_du_fournisseur(self):
        response = self.client.get(f"/api/v1/mouvements/?unite_stock__fournisseur={self.dhl.pk}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["numero_serie"], "008647")
