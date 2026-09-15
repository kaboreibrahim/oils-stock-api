"""
=============================================================================
 apps/dashboard/urls.py
 Monté sous /api/v1/ par core/urls.py. DashboardViewSet n'implémente aucune
 des actions CRUD standard (list/create/retrieve/...) — SimpleRouter ne pose
 donc que les routes des @action déclarées :

 GET /api/v1/dashboard/stock-dormant/?seuil_jours=90
 GET /api/v1/dashboard/seuils-reappro/
 GET /api/v1/dashboard/sorties-mensuelles/
 GET /api/v1/dashboard/previsions/
=============================================================================
"""

from rest_framework.routers import SimpleRouter

from .views import DashboardViewSet

router = SimpleRouter()
router.register("dashboard", DashboardViewSet, basename="dashboard")

urlpatterns = router.urls
