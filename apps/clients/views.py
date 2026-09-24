"""
=============================================================================
 apps/clients/views.py
 ViewSet fin : valide le format (serializer), délègue tout à ClientService,
 traduit les erreurs métier en réponses HTTP.
=============================================================================
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.common.idempotence import executer_avec_idempotence

from .models import Client
from .permissions import IsEmpotageService, IsMagasinierOrReadOnly
from .serializers import ClientSerializer
from .services import ClientService

TAG = ["Clients"]

_service = ClientService()


@extend_schema_view(
    list=extend_schema(
        tags=TAG,
        summary="Lister les clients",
        description="Ouvert à tous les rôles authentifiés. Filtre : `actif` · recherche : `code`, `nom`.",
    ),
    retrieve=extend_schema(tags=TAG, summary="Détail d'un client"),
    create=extend_schema(
        tags=TAG,
        summary="Créer un client",
        description="Réservé aux rôles **MAGASINIER** et **ADMIN**.",
        examples=[
            OpenApiExample(
                "Requête",
                value={"code": "SOFIT", "nom": "Société Ivoirienne des Textiles", "pays": "Côte d'Ivoire"},
                request_only=True,
            ),
        ],
    ),
    update=extend_schema(
        tags=TAG, summary="Modifier un client", description="Réservé aux rôles **MAGASINIER** et **ADMIN**.",
    ),
    partial_update=extend_schema(
        tags=TAG, summary="Modifier partiellement un client", description="Réservé aux rôles **MAGASINIER** et **ADMIN**.",
    ),
    destroy=extend_schema(
        tags=TAG,
        summary="Supprimer un client",
        description=(
            "Réservé aux rôles **MAGASINIER** et **ADMIN**. Suppression logique "
            "(`deleted_at`) — les sorties déjà rattachées restent consultables."
        ),
    ),
)
class ClientViewSet(GenericViewSet):
    """Lecture pour tous ; écriture pour magasinier et admin. Tout passe par ClientService."""

    serializer_class = ClientSerializer
    permission_classes = [IsMagasinierOrReadOnly]
    search_fields = ["code", "nom"]
    filterset_fields = ["actif"]
    ordering_fields = ["nom", "code", "created_at"]

    def get_permissions(self):
        # Intégration EmpotaveV2 (appels serveur à serveur, sans JWT) : lecture
        # seule, nécessaire pour peupler le select "société cliente" côté
        # EmpotaveV2. Écriture reste réservée au frontend humain.
        if self.action in {"list", "retrieve"}:
            return [(IsMagasinierOrReadOnly | IsEmpotageService)()]
        return super().get_permissions()

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
            client = _service.obtenir(pk)
        except Client.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(client).data)

    def create(self, request):
        def executer():
            # Validation à l'intérieur : un rejeu (même Idempotency-Key) ne
            # doit jamais revalider — voir SortieViewSet.create pour le détail.
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            client = _service.creer(serializer.validated_data, request.user)
            return status.HTTP_201_CREATED, self.get_serializer(client).data

        try:
            statut_code, corps = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(corps, status=statut_code)

    def update(self, request, pk=None, partial=False):
        try:
            client = _service.obtenir(pk)
        except Client.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        def executer():
            serializer = self.get_serializer(client, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            client_modifie = _service.modifier(client, serializer.validated_data, request.user)
            return status.HTTP_200_OK, self.get_serializer(client_modifie).data

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
            client = _service.obtenir(pk)
        except Client.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        _service.supprimer(client, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
