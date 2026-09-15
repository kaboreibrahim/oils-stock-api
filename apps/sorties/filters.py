"""
=============================================================================
 apps/sorties/filters.py
 Filtre dédié pour la période (date_sortie) — les autres filtres (client,
 statut) suffisent en correspondance exacte via filterset_fields ailleurs
 dans le projet, mais une plage de dates a besoin d'un FilterSet explicite.
=============================================================================
"""

import django_filters

from .models import Sortie


class SortieFilter(django_filters.FilterSet):
    date_debut = django_filters.DateFilter(field_name="date_sortie", lookup_expr="gte")
    date_fin = django_filters.DateFilter(field_name="date_sortie", lookup_expr="lte")

    class Meta:
        model = Sortie
        fields = ["client", "statut"]
