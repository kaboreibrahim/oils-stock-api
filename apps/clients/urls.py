"""
=============================================================================
 apps/clients/urls.py
 Monté sous /api/v1/ par core/urls.py -> /api/v1/clients/...
 Lecture : tous · écriture : magasinier + admin.
=============================================================================
"""

from rest_framework.routers import SimpleRouter

from .views import ClientViewSet

router = SimpleRouter()
router.register("clients", ClientViewSet, basename="client")

urlpatterns = router.urls
