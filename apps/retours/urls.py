"""
=============================================================================
 apps/retours/urls.py
 Monté sous /api/v1/ par core/urls.py -> /api/v1/retours/
 Une seule route, pas de router (pas de CRUD, pas de modèle — voir services.py).
=============================================================================
"""

from django.urls import path

from .views import RetourView

urlpatterns = [
    path("retours/", RetourView.as_view(), name="retour"),
]
