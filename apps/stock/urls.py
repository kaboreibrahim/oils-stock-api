"""
=============================================================================
 apps/stock/urls.py
 Monté sous /api/v1/ par core/urls.py -> /api/v1/unites/... + /api/v1/mouvements/...
 Lecture seule (l'écriture sur UniteStock arrive via apps.sorties/apps.retours
 et, au Jalon 3/4, apps.receptions ; MouvementStock n'est jamais écrit ici).
=============================================================================
"""

from rest_framework.routers import SimpleRouter

from .views import MouvementStockViewSet, UniteStockViewSet

router = SimpleRouter()
router.register("unites", UniteStockViewSet, basename="unite")
router.register("mouvements", MouvementStockViewSet, basename="mouvement")

urlpatterns = router.urls
