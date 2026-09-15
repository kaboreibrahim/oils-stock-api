"""
=============================================================================
 apps/users/urls.py
 Monté sous /api/v1/ par core/urls.py (préfixes posés ici, pas par core/urls.py,
 pour pouvoir mélanger routes d'authentification et routeur DRF dans un seul
 include() — même pattern que apps.sorties.urls, voir son commentaire).

 ROUTES JETONS/MOT DE PASSE/COURANT -> /api/v1/auth/...
 GESTION DES COMPTES (Jalon 6)       -> /api/v1/users/... (admin uniquement)
=============================================================================
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    ConfirmerReinitialisationView,
    DemanderReinitialisationView,
    LoginView,
    LogoutView,
    MeView,
    TokenRefreshView,
    UserViewSet,
)

router = SimpleRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    # ── Jetons JWT ────────────────────────────────────────────
    # POST /api/v1/auth/token/          {username, password} -> {access, refresh}
    path("auth/token/", LoginView.as_view(), name="token-obtain-pair"),
    # POST /api/v1/auth/token/refresh/  {refresh} -> {access, refresh}
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    # POST /api/v1/auth/logout/  {refresh} -> 205, jeton mis sur liste noire
    path("auth/logout/", LogoutView.as_view(), name="logout"),

    # ── Mot de passe oublié ──────────────────────────────────
    # POST /api/v1/auth/password/reset/          {email} -> code envoyé par e-mail
    path("auth/password/reset/", DemanderReinitialisationView.as_view(), name="password-reset-request"),
    # POST /api/v1/auth/password/reset/confirm/  {email, code, new_password, confirm_password}
    path(
        "auth/password/reset/confirm/",
        ConfirmerReinitialisationView.as_view(),
        name="password-reset-confirm",
    ),

    # ── Utilisateur courant ──────────────────────────────────
    # GET /api/v1/auth/me/  utilisateur courant + rôle
    path("auth/me/", MeView.as_view(), name="me"),

    # ── Gestion des comptes (Jalon 6, admin uniquement) ──────
    *router.urls,
]
