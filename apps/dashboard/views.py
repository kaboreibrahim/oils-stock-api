"""
=============================================================================
 apps/dashboard/views.py
 ViewSet fin, aucune écriture : chaque @action délègue son calcul à
 DashboardService et ne fait que valider les paramètres / traduire les
 erreurs métier en réponses HTTP (même répartition que le reste du projet).
=============================================================================
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from .permissions import IsAuthenticated, IsEmpotageService
from .serializers import (
    PrevisionSerializer,
    SeuilReapproSerializer,
    SortiesMensuellesSerializer,
    StockDormantSerializer,
)
from .services import DashboardService

TAG = ["Tableau de bord"]

_service = DashboardService()

SEUIL_JOURS_DEFAUT = 90


class DashboardViewSet(GenericViewSet):
    """Quatre rapports en lecture seule, ouverts à tous les rôles
    authentifiés — voir DashboardService pour les formules."""

    permission_classes = [IsAuthenticated | IsEmpotageService]

    @extend_schema(
        tags=TAG,
        summary="Stock dormant",
        description=(
            "Unités actuellement EN_STOCK dont la dernière activité (dernière sortie, ou "
            "date d'entrée si jamais sortie) remonte à plus de `seuil_jours` jours. "
            "`valeur_immobilisee` est `null` si le fournisseur n'a pas de coût unitaire "
            "configuré pour ce type — jamais une valeur inventée."
        ),
        parameters=[
            OpenApiParameter(
                "seuil_jours", int, description=f"Nombre de jours d'inactivité, défaut {SEUIL_JOURS_DEFAUT}.",
            ),
        ],
    )
    @action(detail=False, methods=["get"], url_path="stock-dormant")
    def stock_dormant(self, request):
        brut = request.query_params.get("seuil_jours", SEUIL_JOURS_DEFAUT)
        try:
            seuil_jours = int(brut)
        except (TypeError, ValueError):
            return Response(
                {"detail": ["« seuil_jours » doit être un nombre entier."]}, status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            resultat = _service.lister_stock_dormant(seuil_jours)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        page = self.paginate_queryset(resultat)
        serializer = StockDormantSerializer(page if page is not None else resultat, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(
        tags=TAG,
        summary="Seuils de réapprovisionnement (effectifs)",
        description=(
            "Une ligne par (fournisseur, type d'article). Le seuil manuel garde toujours la "
            "priorité ; à défaut, calculé automatiquement dès que le fournisseur a un délai de "
            "livraison et au moins un historique de sortie pour ce type — voir "
            "DashboardService.seuil_effectif. Non paginé (liste bornée : nb fournisseurs × 2)."
        ),
    )
    @action(detail=False, methods=["get"], url_path="seuils-reappro")
    def seuils_reappro(self, request):
        serializer = SeuilReapproSerializer(_service.lister_seuils_reappro(), many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=TAG,
        summary="Sorties mensuelles par type d'article",
        description=(
            "12 mois glissants, une série par type d'article, plus une moyenne mobile sur 3 "
            "mois par série (`null` sur les deux premiers mois de la fenêtre)."
        ),
    )
    @action(detail=False, methods=["get"], url_path="sorties-mensuelles")
    def sorties_mensuelles(self, request):
        return Response(SortiesMensuellesSerializer(_service.sorties_mensuelles()).data)

    @extend_schema(
        tags=TAG,
        summary="Prévisions et recommandations de commande",
        description=(
            "Une ligne par (fournisseur, type d'article), triée par `jours_avant_rupture` "
            "croissant (les lignes sans rythme de sortie récent, donc sans projection "
            "fiable, sont triées en dernier). Non paginé."
        ),
    )
    @action(detail=False, methods=["get"])
    def previsions(self, request):
        serializer = PrevisionSerializer(_service.previsions(), many=True)
        return Response(serializer.data)
