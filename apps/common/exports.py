"""
=============================================================================
 apps/common/exports.py
 Export CSV partagé (Jalon 6, §09 « Exports CSV / PDF », ouvert à tous les
 rôles authentifiés) — utilisé par les @action /export/ des ViewSets en
 lecture (unités, mouvements, sorties, réceptions). Exporte TOUTES les lignes
 correspondant aux filtres courants, pas seulement la page affichée.
=============================================================================
"""

import csv

from django.http import HttpResponse
from django.utils import timezone


def exporter_csv(queryset, colonnes: list[tuple[str, callable]], prefixe_fichier: str) -> HttpResponse:
    """`colonnes` : liste de (en-tête, fonction extrayant la valeur d'une ligne).

    Séparateur `;` (pas `,`) et BOM UTF-8 en tête : Excel en français
    n'affiche sinon ni les accents ni les colonnes correctement.
    """
    nom_fichier = f"{prefixe_fichier}-{timezone.now():%Y-%m-%d}.csv"
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{nom_fichier}"'
    response.write("﻿")  # BOM — sans lui Excel interprète le fichier en Latin-1, accents cassés
    writer = csv.writer(response, delimiter=";")
    writer.writerow([entete for entete, _ in colonnes])
    for ligne in queryset:
        valeurs = [extraire(ligne) for _, extraire in colonnes]
        writer.writerow(["" if v is None else v for v in valeurs])
    return response
