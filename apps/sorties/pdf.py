"""
=============================================================================
 apps/sorties/pdf.py
 Génération du bon de sortie (PDF) — reportlab, pur Python (pas de moteur
 HTML->PDF système à installer, contrairement à WeasyPrint).
=============================================================================
"""

import io
from collections import Counter
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TYPE_LABELS = {"FLEXITANK": "Flexitank", "HEATING_PAD": "Heating pad"}

# Logo affiché en en-tête du bon — à côté du fichier plutôt que dans un
# dossier `static/` Django : pour l'instant utilisé uniquement ici, pas
# collecté ni servi comme fichier statique.
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "oils-of-africa-logo.png"


def _entete(titre_style, soustitre_style, reference: str) -> list:
    """Logo (si présent) + titre alignés sur une ligne, puis la référence en
    dessous. Ne plante jamais si le logo est absent (déploiement incomplet,
    fichier déplacé) — le bon reste utilisable, juste sans logo."""
    titre = Paragraph("Oils of Africa — Bon de sortie", titre_style)
    if LOGO_PATH.exists():
        logo = Image(str(LOGO_PATH), width=18 * mm, height=18 * mm)
        entete = Table([[logo, titre]], colWidths=[22 * mm, 138 * mm])
        entete.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
        ]))
        elements = [entete]
    else:
        elements = [titre]
    elements.append(Paragraph(reference, soustitre_style))
    return elements


def _tableau_repartition(label_style, lignes) -> list:
    """Tableau séparé récapitulant le nombre d'unités sorties par type
    (Flexitank / Heating pad) — demandé en plus du détail unité par unité."""
    compte = Counter(ligne.unite_stock.type_article for ligne in lignes)
    lignes_tableau = [["Type", "Quantité sortie"]] + [
        [TYPE_LABELS.get(type_article, type_article), str(compte[type_article])]
        for type_article in TYPE_LABELS
        if compte[type_article]
    ]
    lignes_tableau.append(["Total", str(len(lignes))])

    table = Table(lignes_tableau, colWidths=[100 * mm, 40 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eefc")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.7, colors.HexColor("#c3cbd6")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde3ec")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [Paragraph("Répartition par type", label_style), Spacer(1, 3 * mm), table]


def _bloc_signature(label_style, texte_style) -> list:
    """Bloc de validation en pied de bon — nom, date et un encadré vide assez
    grand pour signer à la main sur l'exemplaire imprimé."""
    ligne_nom_date = Table(
        [["Gestionnaire de Stock :", "", "Date :", ""]],
        colWidths=[42 * mm, 48 * mm, 18 * mm, 30 * mm],
    )
    ligne_nom_date.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (1, 0), (1, 0), 0.7, colors.black),
        ("LINEBELOW", (3, 0), (3, 0), 0.7, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    case_signature = Table(
        [["Signature :", ""]], colWidths=[42 * mm, 96 * mm], rowHeights=[22 * mm],
    )
    case_signature.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (1, 0), (1, 0), 0.7, colors.HexColor("#c3cbd6")),
        ("TOPPADDING", (0, 0), (0, 0), 4),
    ]))

    return [
        Paragraph("Validation", label_style),
        Spacer(1, 3 * mm),
        ligne_nom_date,
        Spacer(1, 6 * mm),
        case_signature,
    ]


def generer_bon_de_sortie_pdf(sortie, lignes) -> io.BytesIO:
    """Construit le PDF du bon de sortie d'une `Sortie` VALIDEE et renvoie un
    buffer positionné au début, prêt à être servi via FileResponse."""
    lignes = list(lignes)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
        title=f"Bon de sortie {sortie.reference}",
    )
    styles = getSampleStyleSheet()
    titre_style = ParagraphStyle("Titre", parent=styles["Heading1"], fontSize=16, spaceAfter=2)
    soustitre_style = ParagraphStyle("SousTitre", parent=styles["Normal"], textColor=colors.HexColor("#5b6472"))
    validation_style = ParagraphStyle("Validation", parent=styles["Heading3"], fontSize=11, spaceAfter=0)

    elements = _entete(titre_style, soustitre_style, sortie.reference)
    elements.append(Spacer(1, 8 * mm))

    infos = [
        ["Client", sortie.client.nom],
        ["Projet", sortie.projet],
        ["TRD", sortie.trd],
        ["Date de sortie", sortie.date_sortie.strftime("%d/%m/%Y")],
        ["Nombre d'unités", str(len(lignes))],
    ]
    table_infos = Table(infos, colWidths=[40 * mm, 120 * mm])
    table_infos.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(table_infos)
    elements.append(Spacer(1, 8 * mm))
    elements.extend(_tableau_repartition(validation_style, lignes))
    elements.append(Spacer(1, 10 * mm))

    entetes = ["Numéro de série", "Type", "Fournisseur"]
    lignes_tableau = [entetes] + [
        [
            ligne.unite_stock.numero_serie,
            TYPE_LABELS.get(ligne.unite_stock.type_article, ligne.unite_stock.type_article),
            ligne.unite_stock.fournisseur.code,
        ]
        for ligne in lignes
    ]
    table_unites = Table(lignes_tableau, colWidths=[70 * mm, 45 * mm, 45 * mm], repeatRows=1)
    table_unites.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eefc")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde3ec")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(table_unites)
    elements.append(Spacer(1, 14 * mm))
    elements.extend(_bloc_signature(validation_style, soustitre_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer
