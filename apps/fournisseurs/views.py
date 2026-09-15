"""
=============================================================================
 apps/fournisseurs/views.py
 ViewSet fin : valide le format (serializer), délègue tout à
 FournisseurService, traduit les erreurs métier en réponses HTTP.
=============================================================================
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.common.idempotence import executer_avec_idempotence

from .models import Fournisseur
from .permissions import IsAdminOrReadOnly
from .serializers import FournisseurSerializer, ProfilExtractionSerializer
from .services import FournisseurService

TAG = ["Fournisseurs"]

_service = FournisseurService()


@extend_schema_view(
    list=extend_schema(
        tags=TAG,
        summary="Lister les fournisseurs",
        description="Ouvert à tous les rôles authentifiés. Filtres : `actif`, `pays` · recherche : `code`, `nom`.",
    ),
    retrieve=extend_schema(tags=TAG, summary="Détail d'un fournisseur"),
    create=extend_schema(
        tags=TAG,
        summary="Créer un fournisseur",
        description="Réservé au rôle **ADMIN**.",
        examples=[
            OpenApiExample(
                "Requête",
                value={"code": "EBONT", "nom": "Qingdao Ebont Packaging Technology", "pays": "Chine"},
                request_only=True,
            ),
        ],
    ),
    update=extend_schema(tags=TAG, summary="Modifier un fournisseur", description="Réservé au rôle **ADMIN**."),
    partial_update=extend_schema(
        tags=TAG, summary="Modifier partiellement un fournisseur", description="Réservé au rôle **ADMIN**.",
    ),
    destroy=extend_schema(
        tags=TAG,
        summary="Supprimer un fournisseur",
        description=(
            "Réservé au rôle **ADMIN**. Suppression logique (`deleted_at`) — "
            "le fournisseur disparaît des listes mais les unités de stock déjà "
            "rattachées restent consultables. Voir `apps.common.models.SoftDeleteModel`."
        ),
    ),
)
class FournisseurViewSet(GenericViewSet):
    """Lecture pour tous ; écriture réservée à l'admin. Tout passe par FournisseurService."""

    serializer_class = FournisseurSerializer
    permission_classes = [IsAdminOrReadOnly]
    search_fields = ["code", "nom"]
    filterset_fields = ["actif", "pays"]
    ordering_fields = ["nom", "code", "created_at"]

    def get_queryset(self):
        return _service.lister()

    def list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            fournisseur = _service.obtenir(pk)
        except Fournisseur.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(fournisseur).data)

    def create(self, request):
        def executer():
            # Validation à l'intérieur : un rejeu (même Idempotency-Key) ne
            # doit jamais revalider — voir SortieViewSet.create pour le détail.
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            fournisseur = _service.creer(serializer.validated_data, request.user)
            return status.HTTP_201_CREATED, self.get_serializer(fournisseur).data

        try:
            statut_code, corps = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(corps, status=statut_code)

    def update(self, request, pk=None, partial=False):
        try:
            fournisseur = _service.obtenir(pk)
        except Fournisseur.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        def executer():
            serializer = self.get_serializer(fournisseur, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            fournisseur_modifie = _service.modifier(fournisseur, serializer.validated_data, request.user)
            return status.HTTP_200_OK, self.get_serializer(fournisseur_modifie).data

        try:
            statut_code, corps = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(corps, status=statut_code)

    def partial_update(self, request, pk=None):
        return self.update(request, pk=pk, partial=True)

    def destroy(self, request, pk=None):
        try:
            fournisseur = _service.obtenir(pk)
        except Fournisseur.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        _service.supprimer(fournisseur, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=TAG, methods=["GET"], summary="Profil d'extraction d'un fournisseur",
        description="Ouvert à tous les rôles authentifiés.",
    )
    @extend_schema(
        tags=TAG,
        methods=["PUT"],
        summary="Modifier le profil d'extraction",
        description=(
            "Réservé au rôle **ADMIN**. Pilote l'extraction automatique des PDF d'arrivage "
            "(Jalon 4) — mode de lecture, expression régulière du numéro de série, type "
            "d'article par défaut. Laisser `regex_numero_serie` vide retombe sur une détection "
            "générique (revue manuelle systématique, voir apps.receptions.extraction)."
        ),
        examples=[
            OpenApiExample(
                "Requête",
                value={"mode_extraction": "GRILLE", "regex_numero_serie": r"24E\d{10}A\d{3}", "type_article_defaut": "FLEXITANK"},
                request_only=True,
            ),
        ],
    )
    @action(detail=True, methods=["get", "put"], url_path="profil-extraction")
    def profil_extraction(self, request, pk=None):
        try:
            fournisseur = _service.obtenir(pk)
        except Fournisseur.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if request.method == "GET":
            return Response(ProfilExtractionSerializer(fournisseur).data)

        serializer = ProfilExtractionSerializer(fournisseur, data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            fournisseur = _service.modifier(fournisseur, serializer.validated_data, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ProfilExtractionSerializer(fournisseur).data)
