"""
=============================================================================
 apps/receptions/urls.py
 Monté sous /api/v1/ par core/urls.py -> /api/v1/receptions/...
 SimpleRouter couvre le CRUD + les @action (lignes, lignes/plage, valider,
 annuler) ; la sous-ressource lignes/{id}/ (suppression) est la seule route
 imbriquée, via une vue dédiée (voir views.py — même pattern qu'apps.sorties).
=============================================================================
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import LigneReceptionDetailView, ReceptionViewSet

router = SimpleRouter()
router.register("receptions", ReceptionViewSet, basename="reception")

urlpatterns = [
    path(
        "receptions/<uuid:reception_id>/lignes/<uuid:ligne_id>/",
        LigneReceptionDetailView.as_view(),
        name="reception-ligne-detail",
    ),
    *router.urls,
]
