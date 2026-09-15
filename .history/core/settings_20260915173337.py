"""
=============================================================================
 core/settings.py
 Configuration Django — Oils of Africa Stock (API).

 Les valeurs sensibles et propres à l'environnement sont lues dans un
 fichier .env (voir .env.example). Rien de secret n'est versionné.
 Ce fichier ne contient AUCUNE logique métier — voir apps/<domaine>/.
=============================================================================
"""

from datetime import timedelta
from pathlib import Path

import environ
from corsheaders.defaults import default_headers

from core.swagger import SPECTACULAR_SETTINGS  # noqa: F401 (réexporté pour Django)

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000"]),
    TIME_ZONE=(str, "UTC"),
    EMAIL_BACKEND=(str, "django.core.mail.backends.console.EmailBackend"),
    EMAIL_HOST=(str, ""),
    EMAIL_PORT=(int, 587),
    EMAIL_USE_TLS=(bool, True),
    EMAIL_HOST_USER=(str, ""),
    EMAIL_HOST_PASSWORD=(str, ""),
    DEFAULT_FROM_EMAIL=(str, "Oils of Africa Stock <no-reply@oils-of-africa.local>"),
    VAPID_PUBLIC_KEY=(str, ""),
    VAPID_PRIVATE_KEY=(str, ""),
    VAPID_CLAIM_EMAIL=(str, ""),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Durcissement HTTPS, activé automatiquement dès que DEBUG=False (jamais en
# dev, où le site tourne en HTTP simple) — suppose que le domaine de
# production a déjà un certificat SSL valide (AutoSSL/Let's Encrypt) : sans
# ça, SECURE_SSL_REDIRECT provoquerait une boucle de redirection.
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG


# Applications

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
]

# Apps métier, regroupées sous apps/ et découpées par domaine.
LOCAL_APPS = [
    "apps.common",
    "apps.users",
    "apps.fournisseurs",
    "apps.clients",
    "apps.stock",
    "apps.sorties",
    "apps.retours",
    "apps.receptions",
    "apps.dashboard",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# runserver_plus (Jalon 5) — sert l'API en HTTPS avec un certificat existant
# pour le scan mobile en HTTPS local (getUserMedia exige un contexte sécurisé).
# Jamais en production : DEBUG y est toujours False.
if DEBUG:
    INSTALLED_APPS += ["django_extensions"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Sert les fichiers statiques directement depuis l'app WSGI — nécessaire
    # en hébergement mutualisé (Passenger) où DEBUG=False désactive le
    # service natif de `staticfiles`, sans dépendre d'une config Apache
    # spécifique à l'hébergeur. Toujours juste après SecurityMiddleware
    # (recommandation WhiteNoise), avant tout le reste.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"


# Base de données — PostgreSQL, via DATABASE_URL dans le .env
# ex. postgres://oils_stock:motdepasse@127.0.0.1:5432/oils_stock

DATABASES = {"default": env.db("DATABASE_URL")}


# Authentification

AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Django REST Framework

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        # Par IP (l'endpoint de demande ne sait volontairement pas si le
        # compte existe, donc pas de limite par compte possible).
        "password_reset_request": "5/hour",
        # Le vrai risque : brute-forcer le code à 6 chiffres.
        "password_reset_confirm": "10/hour",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,  # un refresh déjà échangé ne peut pas être rejoué
}


# CORS — origines autorisées pour le frontend Next.js

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# Tunnels zrok (accès distant / test sur téléphone) : le sous-domaine change à
# chaque `zrok share`, donc on autorise tout `*.share.zrok.io` par expression
# régulière plutôt que de lister une origine qui sera périmée au prochain
# redémarrage. Même esprit que `allowedDevOrigins` côté Next.
CORS_ALLOWED_ORIGIN_REGEXES = [r"^https://[a-z0-9-]+\.share\.zrok\.io$"]

# CSRF_TRUSTED_ORIGINS protège les vues à session (l'admin Django, visité
# directement sur le domaine de l'API) — l'API elle-même n'en a pas besoin
# (authentification par JWT, sans cookie de session). Le domaine de l'API en
# production doit y figurer, sinon la connexion à /admin/ échoue en 403
# derrière un proxy qui termine le TLS (Origin vu par Django ≠ domaine réel).
CSRF_TRUSTED_ORIGINS = ["https://*.share.zrok.io", *env("CSRF_TRUSTED_ORIGINS")]

# En-tête personnalisé du moteur de synchro hors-ligne (Phase 2 PWA) — sans
# ceci, django-cors-headers bloque silencieusement le preflight et l'échec ne
# se voit que dans un vrai navigateur (les tests APITestCase contournent CORS).
CORS_ALLOW_HEADERS = [*default_headers, "idempotency-key"]


# E-mail — réinitialisation de mot de passe (code à 6 chiffres). Par défaut
# (aucune variable renseignée), les e-mails sont juste affichés dans la
# console — utile en dev/CI sans compte SMTP réel. En test (`manage.py test`),
# Django bascule automatiquement sur un backend en mémoire, jamais le vrai SMTP.

EMAIL_BACKEND = env("EMAIL_BACKEND")
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = env("EMAIL_PORT")
EMAIL_USE_TLS = env("EMAIL_USE_TLS")
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")


# Web push (notifications navigateur) — paire de clés VAPID. Générer avec
# `npx web-push generate-vapid-keys` (le dépôt frontend a déjà Node). Sans
# clés renseignées, seules les notifications in-app fonctionnent :
# NotificationService saute l'envoi web push (un simple warning au log), rien
# ne casse. VAPID_CLAIM_EMAIL = un `mailto:` de contact de l'exploitant.

VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY")
VAPID_CLAIM_EMAIL = env("VAPID_CLAIM_EMAIL")


# Internationalisation

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True


# Fichiers statiques

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise : noms de fichiers hachés (cache-busting) + compression gzip/brotli
# à la collecte (`manage.py collectstatic`). Uniquement les statiques (admin,
# Swagger UI) — les fichiers médias (ci-dessous) n'y transitent jamais.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Fichiers déposés par les utilisateurs (PDF d'arrivage — Jalon 4). Le
# mapping `static(MEDIA_URL, ...)` dans core/urls.py n'est actif qu'en DEBUG
# et n'est qu'une commodité de dev (accès direct à un fichier dans le
# navigateur) — l'application elle-même ne l'utilise jamais : le seul point
# d'accès réel est `GET /api/v1/receptions/{id}/fichier/`, qui lit le fichier
# depuis le disque et le renvoie via `FileResponse` (voir apps/receptions/views.py,
# décision prise au Jalon 4 pour éviter tout souci CORS sur une URL média
# brute). Rien à mettre en place côté serveur de fichiers pour cette
# fonctionnalité en production.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
