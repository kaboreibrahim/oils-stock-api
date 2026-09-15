"""
=============================================================================
 apps/stock/views.py
 ViewSets fins, lecture seule — délèguent à UniteStockService /
 MouvementStockService. L'écriture sur UniteStock passe par apps.sorties /
 apps.retours / apps.receptions, jamais par ces endpoints.
=============================================================================
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.common.exports import exporter_csv

from .models import MouvementStock, UniteStock
from .permissions import IsAuthenticated
from .serializers import CandidatScanSerializer, MouvementStockSerializer, UniteStockSerializer
from .services import MouvementStockService, UniteStockService

TAG = ["Stock"]
MOUVEMENTS_TAG = ["Mouvements de stock"]

_service = UniteStockService()
_mouvements_service = MouvementStockService()


@extend_schema_view(
    list=extend_schema(
        tags=TAG,
        summary="Lister les unités de stock",
        description=(
            "Ouvert à tous les rôles authentifiés. Filtres : `type_article` "
            "(`FLEXITANK`/`HEATING_PAD`), `statut` (`EN_STOCK`/`SORTIE`), "
            "`fournisseur`, `sortie`, `reception` · recherche : `numero_serie`, `code_interne`, `reference_lot`."
        ),
    ),
    retrieve=extend_schema(
        tags=TAG,
        summary="Détail d'une unité de stock",
        description="Fiche d'une unité par son identifiant interne (UUID).",
    ),
)
class UniteStockViewSet(GenericViewSet):
    """Lecture seule — l'écriture passe par les flux Reception/Sortie/Retour."""

    serializer_class = UniteStockSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["numero_serie", "code_interne", "reference_lot"]
    filterset_fields = ["type_article", "statut", "fournisseur", "sortie", "reception"]
    ordering_fields = ["date_entree", "numero_serie"]

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
            unite = _service.obtenir(pk)
        except UniteStock.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(unite).data)

    @extend_schema(
        tags=TAG,
        summary="Résoudre un numéro scanné",
        description=(
            "Recherche par `code_interne` **ou** `numero_serie` exact — renvoie une liste "
            "(vide si rien, plusieurs si le numéro est partagé entre fournisseurs, l'appelant "
            "désambiguïse alors — §07 du dossier de conception)."
        ),
        parameters=[OpenApiParameter("q", OpenApiTypes.STR, description="Code interne ou numéro de série exact.")],
    )
    @action(detail=False, methods=["get"])
    def lookup(self, request):
        q = request.query_params.get("q", "")
        queryset = _service.rechercher(q)
        return Response(self.get_serializer(queryset, many=True).data)

    @extend_schema(
        tags=TAG,
        summary="Résoudre une photo prise au scan mobile",
        description=(
            "OCR (Tesseract, Jalon 5) d'une image envoyée en multipart (`image`) — renvoie les "
            "jetons détectés, chacun avec les unités qu'il résout (liste vide si aucune "
            "correspondance : l'utilisateur corrige alors à la main). Les jetons qui résolvent "
            "une vraie unité sont placés en tête."
        ),
        request={"multipart/form-data": {"type": "object", "properties": {"image": {"type": "string", "format": "binary"}}}},
        responses={200: CandidatScanSerializer(many=True)},
    )
    @action(detail=False, methods=["post"])
    def scanner(self, request):
        image_fichier = request.FILES.get("image")
        if not image_fichier:
            return Response({"detail": ["Le champ « image » est obligatoire."]}, status=status.HTTP_400_BAD_REQUEST)
        from PIL import Image, UnidentifiedImageError

        try:
            image = Image.open(image_fichier)
            image.load()  # force la lecture maintenant : une image tronquée lève ici, pas plus tard
        except (UnidentifiedImageError, OSError):
            return Response(
                {"detail": ["Image illisible — reprenez la photo ou saisissez le numéro à la main."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            resultats = _service.resoudre_candidats_image(image)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CandidatScanSerializer(resultats, many=True).data)

    @extend_schema(
        tags=TAG,
        summary="Exporter le stock en CSV",
        description=(
            "Ouvert à tous les rôles authentifiés (§09 du dossier de conception). "
            "Respecte les mêmes filtres/recherche que la liste — exporte TOUTES les "
            "lignes correspondantes, pas seulement la page affichée."
        ),
        responses={200: OpenApiTypes.BINARY},
    )
    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        colonnes = [
            ("Numéro de série", lambda u: u.numero_serie),
            ("Code interne", lambda u: u.code_interne),
            ("Type", lambda u: u.get_type_article_display()),
            ("Fournisseur", lambda u: u.fournisseur.code),
            ("Statut", lambda u: u.get_statut_display()),
            ("Date d'entrée", lambda u: u.date_entree),
            ("Date de sortie", lambda u: u.date_sortie),
            ("Référence lot", lambda u: u.reference_lot),
            ("Emplacement", lambda u: u.emplacement),
            ("Réception", lambda u: u.reception.reference if u.reception else None),
            ("Sortie", lambda u: u.sortie.reference if u.sortie else None),
        ]
        return exporter_csv(queryset, colonnes, "stock")


@extend_schema_view(
    list=extend_schema(
        tags=MOUVEMENTS_TAG,
        summary="Lister les mouvements de stock",
        description=(
            "Journal d'audit immuable — ouvert à tous les rôles authentifiés. "
            "Filtres : `unite_stock`, `type_mouvement`, `sortie`, `reception`, "
            "`unite_stock__fournisseur` (dernières transactions d'un fournisseur)."
        ),
    ),
    retrieve=extend_schema(tags=MOUVEMENTS_TAG, summary="Détail d'un mouvement de stock"),
)
class MouvementStockViewSet(GenericViewSet):
    """Lecture seule — écrit uniquement par les services (sorties, retours, réceptions)."""

    serializer_class = MouvementStockSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["unite_stock", "type_mouvement", "sortie", "reception", "unite_stock__fournisseur"]
    ordering_fields = ["date_mouvement"]

    def get_queryset(self):
        return _mouvements_service.lister()

    def list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            mouvement = _mouvements_service.obtenir(pk)
        except MouvementStock.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(mouvement).data)

    @extend_schema(
        tags=MOUVEMENTS_TAG,
        summary="Exporter les mouvements en CSV",
        description=(
            "Ouvert à tous les rôles authentifiés (§09 du dossier de conception). "
            "Respecte les mêmes filtres que la liste — exporte TOUTES les lignes "
            "correspondantes, pas seulement la page affichée."
        ),
        responses={200: OpenApiTypes.BINARY},
    )
    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        colonnes = [
            ("Numéro de série", lambda m: m.unite_stock.numero_serie),
            ("Type de mouvement", lambda m: m.get_type_mouvement_display()),
            ("Date", lambda m: m.date_mouvement),
            ("Sortie", lambda m: m.sortie.reference if m.sortie else None),
            ("Réception", lambda m: m.reception.reference if m.reception else None),
            ("Utilisateur", lambda m: m.utilisateur.username if m.utilisateur else None),
            ("Commentaire", lambda m: m.commentaire),
        ]
        return exporter_csv(queryset, colonnes, "mouvements")
