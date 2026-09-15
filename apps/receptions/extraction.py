"""
=============================================================================
 apps/receptions/extraction.py
 Moteur d'extraction des numéros de série depuis un PDF d'arrivage —
 pdfplumber (texte + tableaux), avec repli OCR (Jalon 5, pytesseract) pour
 une page sans couche texte exploitable (PDF scanné). Pure logique, aucun
 accès à l'ORM ici — appelée par ReceptionService.extraire.
=============================================================================
"""

import re
from dataclasses import dataclass

from apps.common.ocr import OcrIndisponible, ocriser_image

__all__ = ["OcrIndisponible", "ResultatExtraction", "extraire_pdf", "detecter_plage"]

# Détection générique quand le fournisseur n'a pas de profil (§05 du dossier
# de conception) : jetons alphanumériques ressemblant à un numéro de série.
# Volontairement large — la fiabilité vient du statut A_VERIFIER qui en découle,
# pas de la précision de ce motif.
REGEX_GENERIQUE = re.compile(r"\b[A-Z0-9]{5,24}\b")

# Quantité annoncée dans le document, ex. « 131 SETS » (exemple Ebont réel du
# dossier de conception).
REGEX_QUANTITE = re.compile(r"(\d{1,6})\s*(?:SETS?|UNIT[ÉE]S?|PCS|PIECES?)", re.IGNORECASE)

# En dessous de ce nombre de caractères non blancs, une page est considérée
# sans couche texte exploitable (scannée) — bascule OCR.
SEUIL_TEXTE_MIN = 10

# Résolution de rendu (DPI) avant OCR — compromis précision/temps pour un
# bordereau A4 typique, pas pour un document haute densité.
RESOLUTION_OCR = 300


@dataclass
class ResultatExtraction:
    numeros: list[str]
    generique: bool  # True si aucun profil fournisseur — statut A_VERIFIER en aval
    ocr_utilise: bool  # True si au moins une page a nécessité l'OCR — idem
    quantite_detectee: int | None
    nb_pages: int


def extraire_pdf(fichier, mode: str, regex_numero_serie: str) -> ResultatExtraction:
    """Ouvre `fichier` (déjà un file-like objet Django) avec pdfplumber et en
    extrait les numéros de série selon `mode` (TABLEAU/GRILLE/TEXTE) et le
    motif du profil fournisseur (générique si absent). Une page sans couche
    texte exploitable est passée à l'OCR avant d'appliquer le même motif."""
    import pdfplumber  # import différé : dépendance lourde, inutile hors extraction

    generique = not bool(regex_numero_serie)
    pattern = re.compile(regex_numero_serie, re.IGNORECASE) if regex_numero_serie else REGEX_GENERIQUE

    numeros: list[str] = []
    textes_pages: list[str] = []
    ocr_utilise = False
    fichier.seek(0)
    with pdfplumber.open(fichier) as pdf:
        for page in pdf.pages:
            texte_page = page.extract_text() or ""
            page_scannee = len(texte_page.strip()) < SEUIL_TEXTE_MIN
            if page_scannee:
                texte_page = ocriser_image(page.to_image(resolution=RESOLUTION_OCR).original)
                ocr_utilise = True
            textes_pages.append(texte_page)

            trouve_en_tableau = False
            if mode == "TABLEAU" and not page_scannee:
                # Détection de tableau vectoriel — sans objet sur une page
                # scannée (juste une image, aucune ligne/cellule à détecter).
                for table in page.extract_tables() or []:
                    colonne = _meilleure_colonne(table, pattern)
                    if colonne:
                        numeros.extend(colonne)
                        trouve_en_tableau = True
            if not trouve_en_tableau:
                numeros.extend(pattern.findall(texte_page))

    texte_complet = "\n".join(textes_pages)
    quantite_match = REGEX_QUANTITE.search(texte_complet)
    quantite_detectee = int(quantite_match.group(1)) if quantite_match else None

    return ResultatExtraction(
        numeros=_dedupliquer(numeros), generique=generique, ocr_utilise=ocr_utilise,
        quantite_detectee=quantite_detectee, nb_pages=len(textes_pages),
    )


def _dedupliquer(numeros: list[str]) -> list[str]:
    vus: set[str] = set()
    resultat = []
    for n in numeros:
        n = n.strip()
        if n and n not in vus:
            vus.add(n)
            resultat.append(n)
    return resultat


def _meilleure_colonne(table: list[list[str | None]], pattern: re.Pattern) -> list[str] | None:
    """Une table pdfplumber est une liste de lignes (chacune une liste de
    cellules). On ignore la première ligne (en-tête probable) et on renvoie
    les valeurs de la colonne qui matche le plus le motif — None si aucune
    colonne n'est concluante (le mode TABLEAU retombe alors sur le texte brut)."""
    if not table or len(table) < 2:
        return None
    nb_colonnes = max(len(row) for row in table)
    meilleure: list[str] | None = None
    meilleur_score = 0
    for c in range(nb_colonnes):
        candidates = []
        score = 0
        for row in table[1:]:
            if c >= len(row) or not row[c]:
                continue
            cellule = row[c].strip()
            if pattern.search(cellule):
                score += 1
                candidates.append(cellule)
        if score > meilleur_score:
            meilleur_score, meilleure = score, candidates
    return meilleure


def detecter_plage(numeros: list[str]) -> dict | None:
    """Repère un préfixe commun + un compteur numérique de largeur constante
    parmi `numeros` — filet de sécurité §05 : neutralise une colonne tronquée
    en indiquant à l'utilisateur qu'il peut compléter via /lignes/plage/
    (déjà disponible depuis le Jalon 3). Renvoie None si les numéros ne
    forment pas un lot homogène (préfixe/largeur variables)."""
    if len(numeros) < 2:
        return None
    # Préfixe = tout jusqu'au dernier caractère non chiffre inclus (ex.
    # "24E3231260424A" avant "001" — le préfixe lui-même contient des
    # chiffres) ; groupe optionnel pour un numéro purement numérique (DHL,
    # LAF) où il n'y a aucun caractère non chiffre du tout.
    motif = re.compile(r"^((?:.*\D)?)(\d+)$")
    prefixe_commun = None
    largeur = None
    valeurs: list[int] = []
    for numero in numeros:
        m = motif.match(numero)
        if not m:
            return None
        prefixe, suffixe = m.group(1), m.group(2)
        if prefixe_commun is None:
            prefixe_commun, largeur = prefixe, len(suffixe)
        elif prefixe != prefixe_commun or len(suffixe) != largeur:
            return None
        valeurs.append(int(suffixe))

    debut, fin = min(valeurs), max(valeurs)
    attendu = fin - debut + 1
    return {
        "prefixe": prefixe_commun,
        "debut": debut,
        "fin": fin,
        "largeur": largeur,
        "complet": len(set(valeurs)) == attendu,
        "nb_trouves": len(set(valeurs)),
        "nb_attendus": attendu,
    }
