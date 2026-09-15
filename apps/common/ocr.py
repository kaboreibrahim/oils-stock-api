"""
=============================================================================
 apps/common/ocr.py
 Primitive OCR partagée (Tesseract via pytesseract, Jalon 5) — utilisée par
 apps.receptions (extraction d'un PDF d'arrivage scanné) et apps.stock
 (résolution d'une photo prise au scan mobile). Vit dans apps.common pour
 éviter toute dépendance croisée entre ces deux apps métier (apps.receptions
 dépend déjà de apps.stock ; l'inverse créerait un cycle).
=============================================================================
"""

import os
import shutil

# Emplacements d'installation par défaut du paquet Chocolatey `tesseract` sous
# Windows. Un `choco install` met à jour le PATH machine, mais un processus
# déjà démarré (ex. `runserver` lancé avant l'installation) garde son PATH en
# mémoire jusqu'à son propre redémarrage — `shutil.which` échoue alors même
# si le binaire est bel et bien présent. On retente ces chemins connus avant
# d'abandonner, plutôt que d'exiger un redémarrage de tout l'environnement.
CHEMINS_TESSERACT_WINDOWS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def _resoudre_binaire_tesseract() -> str | None:
    """Chemin du binaire Tesseract — via le PATH courant, sinon (Windows
    seulement) les emplacements d'installation Chocolatey standard."""
    chemin = shutil.which("tesseract")
    if chemin:
        return chemin
    for candidat in CHEMINS_TESSERACT_WINDOWS:
        if os.path.isfile(candidat):
            return candidat
    return None


class OcrIndisponible(Exception):
    """Levée quand Tesseract n'est pas installé sur la machine — à
    l'appelant de la traduire en ValidationError (message déjà en français,
    prêt à être affiché tel quel)."""


def ocriser_image(image) -> str:
    """OCR d'une image PIL (page de PDF rendue, ou photo prise au téléphone)
    via Tesseract. Lève OcrIndisponible si le binaire n'est pas installé,
    plutôt que de laisser remonter l'erreur brute de pytesseract."""
    import pytesseract

    # Ne recherche/écrase le chemin configuré que si pytesseract est encore
    # sur sa valeur par défaut — ne jamais court-circuiter un réglage
    # explicite (ex. PYTESSERACT_TESSERACT_CMD posé ailleurs par l'appelant).
    if pytesseract.pytesseract.tesseract_cmd == "tesseract":
        binaire = _resoudre_binaire_tesseract()
        if binaire:
            pytesseract.pytesseract.tesseract_cmd = binaire

    try:
        return pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrIndisponible(
            "Le moteur OCR (Tesseract) n'est pas installé sur ce serveur — "
            "utilisez la saisie manuelle en attendant."
        ) from exc
