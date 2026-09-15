"""
=============================================================================
 core/urls.py
 Racine des routes — API Oils of Africa Stock

 ADMIN                 -> /admin/
 SANTÉ                  -> /api/health/                    (non versionné)
 AUTH                   -> /api/v1/auth/...                (apps.users.urls)
 COMPTES (Jalon 6)      -> /api/v1/users/...               (apps.users.urls, admin uniquement)
 FOURNISSEURS           -> /api/v1/fournisseurs/...        (apps.fournisseurs.urls)
 CLIENTS                -> /api/v1/clients/...             (apps.clients.urls)
 UNITÉS DE STOCK        -> /api/v1/unites/...               (apps.stock.urls)
 MOUVEMENTS DE STOCK    -> /api/v1/mouvements/...           (apps.stock.urls)
 SORTIES                -> /api/v1/sorties/...              (apps.sorties.urls)
 PROJETS (autocomplete) -> /api/v1/projets/...              (apps.sorties.urls)
 RETOURS                -> /api/v1/retours/...              (apps.retours.urls)
 RÉCEPTIONS             -> /api/v1/receptions/...           (apps.receptions.urls)
 TABLEAU DE BORD        -> /api/v1/dashboard/...             (apps.dashboard.urls)
 NOTIFICATIONS          -> /api/v1/notifications/...          (apps.notifications.urls)
 DOCUMENTATION API      -> /api/schema/, /api/docs/swagger/, /api/docs/redoc/
 FICHIERS (dev)         -> /media/...                       (PDF d'arrivage, DEBUG uniquement)
=============================================================================
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.permissions import AllowAny


def health(_request):
    """Sonde de disponibilité — pas de DRF ici, volontairement toujours public
    et non versionnée (les outils de supervision ne doivent pas suivre v1/v2)."""
    return JsonResponse({"service": "oils-stock-api", "status": "ok"})


# Doc/schéma ouverts sans authentification : ce sont des descriptions de
# l'API, pas des données — la friction d'un token juste pour les consulter
# n'apporterait rien.
open_kwargs = {"permission_classes": [AllowAny]}

# ── Routes versionnées v1 ────────────────────────────────────────────────
v1_urlpatterns = [
    # apps.users.urls pose lui-même ses préfixes ("auth/token/", "users/"...)
    # — pas de préfixe ici, même pattern que apps.sorties.urls (sorties/ +
    # projets/ dans un seul fichier).
    path("", include("apps.users.urls")),
    path("", include("apps.fournisseurs.urls")),
    path("", include("apps.clients.urls")),
    path("", include("apps.stock.urls")),
    path("", include("apps.sorties.urls")),
    path("", include("apps.retours.urls")),
    path("", include("apps.receptions.urls")),
    path("", include("apps.dashboard.urls")),
    path("", include("apps.notifications.urls")),
]

urlpatterns = [
    # ── Administration Django ────────────────────────────────
    path("admin/", admin.site.urls),

    # ── Santé ─────────────────────────────────────────────────
    path("api/health/", health, name="health"),

    # ── API v1 ────────────────────────────────────────────────
    path("api/v1/", include(v1_urlpatterns)),

    # ── Documentation API (Swagger UI / Redoc / schéma OpenAPI) ──
    path("api/schema/", SpectacularAPIView.as_view(**open_kwargs), name="schema"),
    path(
        "api/docs/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema", **open_kwargs),
        name="swagger-ui",
    ),
    path(
        "api/docs/redoc/",
        SpectacularRedocView.as_view(url_name="schema", **open_kwargs),
        name="redoc",
    ),
]

# Fichiers déposés (PDF d'arrivage) — servis par Django seulement en DEBUG,
# comme les fichiers statiques ; pas d'authentification à ce stade (réseau
# local, cohérent avec le reste des accès non sensibles du projet).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
