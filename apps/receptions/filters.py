"""
=============================================================================
 apps/receptions/filters.py
 Filtre dédié pour la période (date_reception) — voir apps.sorties.filters,
 même besoin, même solution (filterset_fields simple ne gère pas une plage).
=============================================================================
"""

import django_filters

from .models import Reception


class ReceptionFilter(django_filters.FilterSet):
    date_debut = django_filters.DateFilter(field_name="date_reception", lookup_expr="gte")
    date_fin = django_filters.DateFilter(field_name="date_reception", lookup_expr="lte")

    class Meta:
        model = Reception
        fields = ["nature", "statut", "fournisseur"]
