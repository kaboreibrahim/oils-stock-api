"""
=============================================================================
 apps/fournisseurs/urls.py
 Monté sous /api/v1/ par core/urls.py -> /api/v1/fournisseurs/...
 Lecture : tous · écriture : admin.
=============================================================================
"""

from rest_framework.routers import SimpleRouter

from .views import FournisseurViewSet

router = SimpleRouter()
router.register("fournisseurs", FournisseurViewSet, basename="fournisseur")

urlpatterns = router.urls
