"""
=============================================================================
 apps/notifications/urls.py
 Monté sous /api/v1/ par core/urls.py.

 GET    /api/v1/notifications/                      liste (filtre ?lu=)
 GET    /api/v1/notifications/non-lus/              {count}
 POST   /api/v1/notifications/{id}/marquer-lu/
 POST   /api/v1/notifications/marquer-tout-lu/      {count}
 GET    /api/v1/notifications/cle-vapid-publique/   {cle}
 POST   /api/v1/notifications/abonnements/          {endpoint, keys:{p256dh, auth}, user_agent?}
 DELETE /api/v1/notifications/abonnements/?endpoint=...
=============================================================================
"""

from rest_framework.routers import SimpleRouter

from .views import NotificationViewSet

router = SimpleRouter()
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = router.urls
