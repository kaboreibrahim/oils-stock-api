"""
=============================================================================
 apps/users/views.py
 Vues d'authentification — une classe par endpoint, documentation Swagger
 complète via drf-spectacular (tags, description, exemples).

 Pas de couche service ici : la logique métier de l'émission/rotation des
 jetons appartient à djangorestframework-simplejwt (BaseTokenObtainPairView /
 BaseTokenRefreshView) ; on ne fait qu'habiller ses vues de nos propres
 classes pour la documentation. UserRepository sert aux futurs écrans de
 gestion des comptes (Jalon 6), pas à ces trois endpoints.
=============================================================================
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from apps.common.permissions import IsAdmin

from .models import User
from .serializers import (
    ConfirmationReinitialisationSerializer,
    CreerUserSerializer,
    DemandeReinitialisationSerializer,
    LoginSerializer,
    LogoutSerializer,
    MeSerializer,
    UserSerializer,
)
from .services import AuthService, PasswordResetService, UserService

TAG = ["Authentification"]
USERS_TAG = ["Comptes utilisateurs"]

_auth_service = AuthService()
_password_reset_service = PasswordResetService()
_user_service = UserService()


class PasswordResetRequestThrottle(AnonRateThrottle):
    """Empêche de spammer l'envoi d'e-mails — par IP, pas par compte (l'endpoint
    ne sait volontairement pas si le compte existe)."""

    scope = "password_reset_request"


class PasswordResetConfirmThrottle(AnonRateThrottle):
    """Le vrai risque ici est le brute-force du code à 6 chiffres."""

    scope = "password_reset_confirm"


# ── Connexion ────────────────────────────────────────────────────────────

@extend_schema(
    tags=TAG,
    summary="Connexion — obtenir un couple de jetons JWT",
    description=(
        "Authentifie par nom d'utilisateur + mot de passe et retourne un "
        "jeton d'accès (30 min) et un jeton de renouvellement (7 jours).\n\n"
        "Un compte supprimé (`deleted_at` renseigné) ou désactivé "
        "(`is_active=False`) est invisible à la connexion — la réponse est "
        "la même que des identifiants incorrects. **Le message est le même "
        "dans tous les cas** : ne révèle jamais si c'est le nom d'utilisateur "
        "ou le mot de passe qui est en cause, ni si le compte existe."
    ),
    request=LoginSerializer,
    responses={
        200: OpenApiResponse(description="Connexion réussie"),
        401: OpenApiResponse(description="Identifiants incorrects"),
    },
    examples=[
        OpenApiExample(
            "Requête",
            value={"username": "admin", "password": "admin1234"},
            request_only=True,
        ),
        OpenApiExample(
            "Connexion réussie",
            value={
                "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            },
            response_only=True,
            status_codes=["200"],
        ),
        OpenApiExample(
            "Identifiants incorrects, compte supprimé ou désactivé",
            value={"detail": "Identifiants incorrects."},
            response_only=True,
            status_codes=["401"],
        ),
    ],
)
class LoginView(APIView):
    """POST /api/v1/auth/token/"""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tokens = _auth_service.connecter(**serializer.validated_data)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(tokens)


# ── Renouvellement du jeton ──────────────────────────────────────────────

@extend_schema(
    tags=TAG,
    summary="Renouveler le jeton d'accès",
    description=(
        "Échange un jeton de renouvellement valide contre un nouveau jeton "
        "d'accès. La rotation est activée : un nouveau `refresh` est "
        "aussi renvoyé, l'ancien devient invalide."
    ),
    examples=[
        OpenApiExample(
            "Requête",
            value={"refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."},
            request_only=True,
        ),
        OpenApiExample(
            "Succès",
            value={
                "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            },
            response_only=True,
            status_codes=["200"],
        ),
        OpenApiExample(
            "Jeton expiré ou invalide",
            value={"detail": "Jeton de renouvellement invalide ou expiré."},
            response_only=True,
            status_codes=["401"],
        ),
    ],
)
class TokenRefreshView(BaseTokenRefreshView):
    """POST /api/v1/auth/token/refresh/"""

    def post(self, request, *args, **kwargs):
        # Réutilise la rotation/liste noire de simplejwt telles quelles (déjà
        # testées) — seul le message d'erreur final est reformulé en français,
        # sans détail technique (jeton rejoué, expiré, invalide : même message).
        try:
            return super().post(request, *args, **kwargs)
        except (InvalidToken, TokenError):
            return Response(
                {"detail": "Jeton de renouvellement invalide ou expiré."},
                status=status.HTTP_401_UNAUTHORIZED,
            )


# ── Utilisateur courant ──────────────────────────────────────────────────

@extend_schema(
    tags=TAG,
    summary="Utilisateur courant",
    description=(
        "Identité et rôle de l'utilisateur authentifié — sert au frontend à "
        "adapter la navigation et les permissions d'écriture "
        "(`ADMIN` / `MAGASINIER` / `LECTURE`)."
    ),
    responses={200: OpenApiResponse(response=MeSerializer)},
    examples=[
        OpenApiExample(
            "Succès",
            value={
                "id": "6e2b1e3a-2f8b-4a41-9b8b-6f7f2f0b2b7e",
                "username": "admin",
                "email": "ibrakdev@gmail.com",
                "first_name": "",
                "last_name": "",
                "role": "ADMIN",
                "is_staff": True,
                "is_superuser": True,
            },
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
class MeView(RetrieveAPIView):
    """GET /api/v1/auth/me/"""

    serializer_class = MeSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


# ── Déconnexion ───────────────────────────────────────────────────────────

@extend_schema(
    tags=TAG,
    summary="Déconnexion — révoquer le jeton de renouvellement",
    description=(
        "Place le `refresh` token sur liste noire : il ne peut plus être "
        "échangé contre un nouvel `access` token.\n\n"
        "Limite connue d'un logout par liste noire (plutôt que par session) : "
        "l'`access` token déjà émis reste valable jusqu'à son expiration "
        "naturelle (30 min maximum)."
    ),
    request=LogoutSerializer,
    responses={
        205: OpenApiResponse(description="Déconnexion réussie — aucun contenu"),
        400: OpenApiResponse(description="Jeton manquant, déjà révoqué ou invalide"),
    },
    examples=[
        OpenApiExample(
            "Requête",
            value={"refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."},
            request_only=True,
        ),
    ],
)
class LogoutView(APIView):
    """POST /api/v1/auth/logout/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            return Response(
                {"detail": "Jeton invalide ou déjà révoqué."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_205_RESET_CONTENT)


# ── Mot de passe oublié ───────────────────────────────────────────────────

@extend_schema(
    tags=TAG,
    summary="Mot de passe oublié — demander un code par e-mail",
    description=(
        "Envoie un code à 6 chiffres (valable 15 minutes, usage unique) à "
        "l'e-mail du compte. **Réponse générique** dans tous les cas — "
        "existence ou non du compte jamais révélée."
    ),
    request=DemandeReinitialisationSerializer,
    responses={200: OpenApiResponse(description="Réponse générique (sécurité)")},
    examples=[
        OpenApiExample("Requête", value={"email": "admin@oils-of-africa.example"}, request_only=True),
        OpenApiExample(
            "Réponse",
            value={"detail": "Si un compte existe avec cet e-mail, un code a été envoyé."},
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
class DemanderReinitialisationView(APIView):
    """POST /api/v1/auth/password/reset/"""

    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRequestThrottle]

    def post(self, request):
        serializer = DemandeReinitialisationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _password_reset_service.demander(serializer.validated_data["email"])
        return Response({"detail": "Si un compte existe avec cet e-mail, un code a été envoyé."})


@extend_schema(
    tags=TAG,
    summary="Mot de passe oublié — confirmer avec le code reçu",
    description=(
        "Vérifie le code à 6 chiffres et applique le nouveau mot de passe. "
        "Au succès, **toutes les sessions existantes de ce compte sont "
        "révoquées** (tous les refresh tokens en circulation sont blacklistés) "
        "— il faut se reconnecter partout."
    ),
    request=ConfirmationReinitialisationSerializer,
    responses={
        200: OpenApiResponse(description="Mot de passe réinitialisé"),
        400: OpenApiResponse(description="Code invalide/expiré, mots de passe différents, ou trop faible"),
    },
    examples=[
        OpenApiExample(
            "Requête",
            value={
                "email": "admin@oils-of-africa.example",
                "code": "123456",
                "new_password": "NouveauMotDePasse123!",
                "confirm_password": "NouveauMotDePasse123!",
            },
            request_only=True,
        ),
        OpenApiExample(
            "Succès",
            value={"detail": "Mot de passe réinitialisé. Reconnectez-vous."},
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
class ConfirmerReinitialisationView(APIView):
    """POST /api/v1/auth/password/reset/confirm/"""

    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetConfirmThrottle]

    def post(self, request):
        serializer = ConfirmationReinitialisationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            _password_reset_service.confirmer(
                email=data["email"], code=data["code"], nouveau_mot_de_passe=data["new_password"],
            )
        except DjangoValidationError as exc:
            try:
                detail = exc.message_dict  # ValidationError construite avec un dict (ex. {"new_password": [...]})
            except AttributeError:
                detail = exc.messages  # ValidationError construite avec un message simple
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Mot de passe réinitialisé. Reconnectez-vous."})


# ── Gestion des comptes (Jalon 6, admin uniquement) ───────────────────────

@extend_schema_view(
    list=extend_schema(
        tags=USERS_TAG,
        summary="Lister les comptes utilisateurs",
        description="Réservé à l'**ADMIN**. Filtres : `role`, `is_active` · recherche : `username`, `email`, `first_name`, `last_name`.",
    ),
    retrieve=extend_schema(tags=USERS_TAG, summary="Détail d'un compte", description="Réservé à l'**ADMIN**."),
    create=extend_schema(
        tags=USERS_TAG,
        summary="Créer un compte",
        description="Réservé à l'**ADMIN**. Le mot de passe initial est fourni ici ; le compte peut le changer ensuite via « mot de passe oublié ».",
        request=CreerUserSerializer,
        examples=[
            OpenApiExample(
                "Requête",
                value={"username": "magasinier2", "password": "MotDePasseInitial123!", "role": "MAGASINIER"},
                request_only=True,
            ),
        ],
    ),
    update=extend_schema(tags=USERS_TAG, summary="Modifier un compte", description="Réservé à l'**ADMIN**. Ne change jamais le mot de passe."),
    partial_update=extend_schema(tags=USERS_TAG, summary="Modifier partiellement un compte", description="Réservé à l'**ADMIN**."),
    destroy=extend_schema(
        tags=USERS_TAG,
        summary="Supprimer un compte",
        description="Réservé à l'**ADMIN**. Suppression logique — refusée sur son propre compte ou le dernier admin actif.",
    ),
)
class UserViewSet(GenericViewSet):
    """CRUD des comptes — entièrement réservé à l'admin. Tout passe par UserService."""

    serializer_class = UserSerializer
    permission_classes = [IsAdmin]
    search_fields = ["username", "email", "first_name", "last_name"]
    filterset_fields = ["role", "is_active"]
    ordering_fields = ["username", "date_joined"]

    def get_queryset(self):
        return _user_service.lister()

    def get_serializer_class(self):
        if self.action == "create":
            return CreerUserSerializer
        return UserSerializer

    def list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = UserSerializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            utilisateur = _user_service.obtenir(pk)
        except User.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(UserSerializer(utilisateur).data)

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            utilisateur = _user_service.creer(serializer.validated_data, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UserSerializer(utilisateur).data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None, partial=False):
        try:
            utilisateur = _user_service.obtenir(pk)
        except User.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = UserSerializer(utilisateur, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            utilisateur = _user_service.modifier(utilisateur, serializer.validated_data, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UserSerializer(utilisateur).data)

    def partial_update(self, request, pk=None):
        return self.update(request, pk=pk, partial=True)

    def destroy(self, request, pk=None):
        try:
            utilisateur = _user_service.obtenir(pk)
        except User.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            _user_service.supprimer(utilisateur, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)
