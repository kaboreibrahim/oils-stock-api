"""
=============================================================================
 core/swagger.py
 Configuration drf-spectacular (schéma OpenAPI -> Swagger UI / Redoc).
 Le routage des pages de doc elles-mêmes reste dans core/urls.py.
=============================================================================
"""

SPECTACULAR_SETTINGS = {
    "TITLE": "Oils of Africa — Stock API",
    "DESCRIPTION": (
        "API de gestion de stock (flexitanks et heating pads sérialisés). "
        "Voir le dossier de conception « Stock Oils of Africa » pour le contexte métier."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    # Plusieurs modèles ont chacun leur propre champ "statut" avec des valeurs
    # différentes (UniteStock.statut, Sortie.statut...) — noms explicites pour
    # éviter que drf-spectacular ne les fasse fusionner sous un même enum.
    "ENUM_NAME_OVERRIDES": {
        "StatutStockEnum": "apps.stock.models.StatutStock",
        "StatutSortieEnum": "apps.sorties.models.StatutSortie",
    },
}
