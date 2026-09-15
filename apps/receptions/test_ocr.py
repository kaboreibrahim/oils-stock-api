"""
=============================================================================
 apps/receptions/test_ocr.py
 Flux : PDF scanné (aucune couche texte) -> OCR -> lignes A_VERIFIER, et
 dégradation propre quand Tesseract n'est pas installé sur la machine.

 `test_extraction_ocr_sur_pdf_scanne` utilise le VRAI Tesseract si résoluble
 (même résolution que l'appli, voir `apps.common.ocr`) — sinon ignoré plutôt
 que faussement rouge : ce n'est pas un test d'environnement, l'app doit
 juste ne pas planter (voir l'autre test, qui lui tourne toujours en mockant
 l'absence du binaire).
=============================================================================
"""

import io
from datetime import date
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas
from rest_framework import status
from rest_framework.test import APITestCase

from apps.common.ocr import _resoudre_binaire_tesseract
from apps.fournisseurs.models import Fournisseur
from apps.stock.models import TypeArticle, UniteStock

TESSERACT_DISPONIBLE = _resoudre_binaire_tesseract() is not None

User = get_user_model()


def pdf_scanne(numeros: list[str]) -> SimpleUploadedFile:
    """PDF composé d'une image rasterisée (aucune couche texte) — dessine les
    numéros avec Pillow, les incruste dans une page PDF via reportlab. Un
    pdfplumber.extract_text() sur ce fichier renvoie toujours une chaîne vide,
    ce qui déclenche le repli OCR (voir apps.receptions.extraction)."""
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    police = ImageFont.load_default(size=32)
    y = 20
    for numero in numeros:
        draw.text((20, y), numero, fill="black", font=police)
        y += 45
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    pdf_buffer = io.BytesIO()
    c = pdfcanvas.Canvas(pdf_buffer, pagesize=(800, 600))
    c.drawImage(ImageReader(image_buffer), 0, 0, width=800, height=600)
    c.save()
    pdf_buffer.seek(0)
    return SimpleUploadedFile("scanne.pdf", pdf_buffer.read(), content_type="application/pdf")


class OcrApiTests(APITestCase):
    def setUp(self):
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.dhl = Fournisseur.objects.create(
            code="DHL", nom="DHL", mode_extraction="TEXTE",
            regex_numero_serie=r"\d{6}", type_article_defaut=TypeArticle.HEATING_PAD,
        )
        self.client.force_authenticate(user=self.magasinier)

    def _creer_arrivage(self, fichier):
        response = self.client.post(
            "/api/v1/receptions/",
            {"nature": "ARRIVAGE", "fournisseur": str(self.dhl.pk), "date_reception": "2026-09-10", "fichier": fichier},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data["id"]

    def test_ocr_indisponible_est_gere_proprement(self):
        """Sans Tesseract installé, l'API doit refuser proprement (400, message
        clair) plutôt que planter (500) — mocké pour ne pas dépendre de l'état
        réel de la machine qui fait tourner les tests."""
        import pytesseract

        reception_id = self._creer_arrivage(pdf_scanne(["008647"]))
        with patch(
            "pytesseract.image_to_string",
            side_effect=pytesseract.TesseractNotFoundError(),
        ):
            response = self.client.post(f"/api/v1/receptions/{reception_id}/extraire/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Tesseract", response.data["detail"][0])

    @skipUnless(TESSERACT_DISPONIBLE, "Tesseract non installé sur cette machine")
    def test_extraction_ocr_sur_pdf_scanne(self):
        reception_id = self._creer_arrivage(pdf_scanne(["008647", "008648", "008649"]))
        response = self.client.post(f"/api/v1/receptions/{reception_id}/extraire/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["ocr_utilise"])
        numeros = {l["numero_serie"] for l in response.data["lignes"]}
        self.assertIn("008647", numeros)
        for ligne in response.data["lignes"]:
            # OCR = confiance moindre, à vérifier même avec un profil qui matche.
            self.assertEqual(ligne["statut_ligne"], "A_VERIFIER")

    @skipUnless(TESSERACT_DISPONIBLE, "Tesseract non installé sur cette machine")
    def test_extraction_ocr_detecte_un_doublon(self):
        UniteStock.objects.create(
            numero_serie="008647", type_article=TypeArticle.HEATING_PAD,
            fournisseur=self.dhl, date_entree=date.today(),
        )
        reception_id = self._creer_arrivage(pdf_scanne(["008647"]))
        response = self.client.post(f"/api/v1/receptions/{reception_id}/extraire/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["lignes"][0]["statut_ligne"], "DOUBLON")
