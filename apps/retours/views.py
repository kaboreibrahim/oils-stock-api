"""
=============================================================================
 apps/retours/views.py
 Une seule route (POST) : enregistrer un retour. Vue fine, valide le format
 (serializer), délègue tout à RetourService.
=============================================================================
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stock.serializers import UniteStockSerializer

from .permissions import IsMagasinierOrReadOnly
from .serializers import RetourSerializer
from .services import RetourService

TAG = ["Retours"]

_service = RetourService()


class RetourView(APIView):
    """`POST /api/v1/retours/` — les unités `SORTIE` listées reviennent `EN_STOCK` ;
    la ou les sorties d'origine restent `VALIDEE` (seules les unités rentrent, voir §06)."""

    permission_classes = [IsMagasinierOrReadOnly]

    @extend_schema(
        tags=TAG,
        summary="Enregistrer un retour",
        description=(
            "Réservé à **MAGASINIER**/**ADMIN**. Chaque unité doit être actuellement "
            "`SORTIE` ; refusé sinon (numéro inconnu, déjà en stock, ambigu entre "
            "fournisseurs)."
        ),
        request=RetourSerializer,
        responses={201: UniteStockSerializer(many=True)},
        examples=[
            OpenApiExample(
                "Requête",
                value={
                    "unites": [{"numero_serie": "008647"}, {"numero_serie": "0309260303041"}],
                    "date_retour": "2026-09-12",
                    "motif": "Renvoi client — projet annulé",
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request):
        serializer = RetourSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            unites = _service.enregistrer(
                serializer.validated_data["unites"],
                serializer.validated_data["date_retour"],
                serializer.validated_data["motif"],
                request.user,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UniteStockSerializer(unites, many=True).data, status=status.HTTP_201_CREATED)
