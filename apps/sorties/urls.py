"""
=============================================================================
 apps/sorties/urls.py
 Monté sous /api/v1/ par core/urls.py -> /api/v1/sorties/... + /api/v1/projets/
 SimpleRouter couvre le CRUD + les @action (lignes, valider, annuler, bon de
 sortie) ; la sous-ressource lignes/{id}/ (suppression) est la seule route
 imbriquée du projet, via une vue dédiée (voir views.py).
=============================================================================
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import LigneSortieDetailView, ProjetAutocompleteView, SortieViewSet

router = SimpleRouter()
router.register("sorties", SortieViewSet, basename="sortie")

urlpatterns = [
    path(
        "sorties/<uuid:sortie_id>/lignes/<uuid:ligne_id>/",
        LigneSortieDetailView.as_view(),
        name="sortie-ligne-detail",
    ),
    path("projets/", ProjetAutocompleteView.as_view(), name="projet-autocomplete"),
    *router.urls,
]
