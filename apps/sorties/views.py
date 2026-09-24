"""
=============================================================================
 apps/sorties/views.py
 ViewSet fin : valide le format (serializer), délègue tout à SortieService,
 traduit les erreurs métier en réponses HTTP. Les actions non-CRUD (lignes,
 valider, annuler, bon de sortie) utilisent @action, seul endroit du projet
 où un besoin réellement imbriqué (sous-ressource lignes/{id}/) justifie en
 plus une vue à part (LigneSortieDetailView, voir urls.py).
=============================================================================
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.common.exports import exporter_csv
from apps.common.idempotence import executer_avec_idempotence

from .filters import SortieFilter
from .models import LigneSortie, Sortie, StatutSortie
from .pdf import generer_bon_de_sortie_pdf
from .permissions import IsAdmin, IsEmpotageService, IsMagasinierOrReadOnly
from .serializers import (
    AjouterLigneSerializer,
    AnnulerSortieSerializer,
    LigneSortieSerializer,
    SortieDetailSerializer,
    SortieSerializer,
)
from .services import SortieService

TAG = ["Sorties"]

_service = SortieService()


@extend_schema_view(
    list=extend_schema(
        tags=TAG,
        summary="Lister les sorties",
        description=(
            "Ouvert à tous les rôles. Filtres : `client`, `statut`, `date_debut`, "
            "`date_fin` · recherche : `reference`, `projet`, `trd`."
        ),
    ),
    retrieve=extend_schema(
        tags=TAG, summary="Détail d'une sortie", description="Inclut les lignes (unités) de la sortie.",
    ),
    create=extend_schema(
        tags=TAG,
        summary="Créer une sortie (brouillon)",
        description="Réservé à **MAGASINIER**/**ADMIN**. Naît au statut `BROUILLON`, référence générée automatiquement.",
        examples=[
            OpenApiExample(
                "Requête",
                value={
                    "client": "3b1b7e2e-2222-4444-8888-000000000001",
                    "projet": "Rénovation dépôt Nord",
                    "trd": "TRD-4471",
                    "date_sortie": "2026-09-10",
                },
                request_only=True,
            ),
        ],
    ),
    update=extend_schema(
        tags=TAG, summary="Modifier l'en-tête d'une sortie", description="Uniquement tant que la sortie est `BROUILLON`.",
    ),
    partial_update=extend_schema(
        tags=TAG, summary="Modifier partiellement l'en-tête", description="Uniquement tant que la sortie est `BROUILLON`.",
    ),
    destroy=extend_schema(
        tags=TAG,
        summary="Supprimer une sortie brouillon",
        description="Suppression logique, uniquement tant que la sortie est `BROUILLON`.",
    ),
)
class SortieViewSet(GenericViewSet):
    """Lecture pour tous ; écriture pour magasinier et admin. Tout passe par SortieService."""

    permission_classes = [IsMagasinierOrReadOnly]
    filterset_class = SortieFilter
    search_fields = ["reference", "projet", "trd"]
    ordering_fields = ["date_sortie", "created_at", "reference"]

    def get_permissions(self):
        # Annuler une sortie déjà validée est réservé à l'admin (Jalon 6 —
        # §09, note * tranchée) : opération sensible sur un document déjà
        # répercuté sur le stock réel. Toutes les autres actions restent
        # magasinier + admin, via permission_classes au niveau de la classe.
        if self.action == "annuler":
            return [IsAdmin()]
        # Intégration EmpotaveV2 (appels serveur à serveur, sans JWT) : ajoutée
        # en OR uniquement sur les actions qu'elle utilise réellement — pas sur
        # update/destroy, qui restent réservées au frontend humain.
        if self.action in {"create", "lignes", "valider"}:
            return [(IsMagasinierOrReadOnly | IsEmpotageService)()]
        return super().get_permissions()

    def get_queryset(self):
        return _service.lister()

    def get_serializer_class(self):
        if self.action in {"retrieve", "valider", "annuler"}:
            return SortieDetailSerializer
        return SortieSerializer

    def list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            sortie = _service.obtenir(pk)
        except Sortie.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(sortie).data)

    def create(self, request):
        def executer():
            # Validation DÉLIBÉRÉMENT à l'intérieur : sur un rejeu (même
            # Idempotency-Key), executer_avec_idempotence() court-circuite
            # avant même d'arriver ici — revalider ici recommencerait une
            # vérification d'unicité sur des données déjà créées par le
            # premier appel et échouerait à tort.
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            sortie = _service.creer(serializer.validated_data, request.user)
            return status.HTTP_201_CREATED, self.get_serializer(sortie).data

        try:
            statut_code, corps = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(corps, status=statut_code)

    def update(self, request, pk=None, partial=False):
        try:
            sortie = _service.obtenir(pk)
        except Sortie.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(sortie, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            sortie = _service.modifier(sortie, serializer.validated_data, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(sortie).data)

    def partial_update(self, request, pk=None):
        return self.update(request, pk=pk, partial=True)

    def destroy(self, request, pk=None):
        try:
            sortie = _service.obtenir(pk)
        except Sortie.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            _service.supprimer(sortie, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Lignes ───────────────────────────────────────────────────────────

    @extend_schema(tags=TAG, methods=["GET"], summary="Lister les unités d'une sortie")
    @extend_schema(
        tags=TAG,
        methods=["POST"],
        summary="Ajouter une unité à une sortie",
        description=(
            "Réservé à MAGASINIER/ADMIN, uniquement tant que la sortie est `BROUILLON`. "
            "Refusé si l'unité n'existe pas ou n'est pas `EN_STOCK`."
        ),
        request=AjouterLigneSerializer,
        examples=[OpenApiExample("Requête", value={"numero_serie": "008647"}, request_only=True)],
    )
    @action(detail=True, methods=["get", "post"], url_path="lignes")
    def lignes(self, request, pk=None):
        try:
            sortie = _service.obtenir(pk)
        except Sortie.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if request.method == "GET":
            queryset = _service.lister_lignes(sortie)
            return Response(LigneSortieSerializer(queryset, many=True).data)

        def executer():
            # Validation à l'intérieur (voir create() ci-dessus) : un rejeu
            # ne doit jamais revalider/ré-exécuter, seulement renvoyer la
            # réponse déjà produite.
            serializer = AjouterLigneSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            ligne = _service.ajouter_ligne(
                sortie,
                serializer.validated_data["numero_serie"],
                request.user,
                fournisseur=serializer.validated_data.get("fournisseur"),
            )
            return status.HTTP_201_CREATED, LigneSortieSerializer(ligne).data

        try:
            statut_code, corps = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(corps, status=statut_code)

    # ── Cycle de vie ─────────────────────────────────────────────────────

    @extend_schema(
        tags=TAG,
        summary="Valider une sortie",
        description="Fait passer les unités `EN_STOCK` → `SORTIE`, écrit les mouvements, rend le bon de sortie disponible.",
        request=None,
    )
    @action(detail=True, methods=["post"])
    def valider(self, request, pk=None):
        try:
            sortie = _service.obtenir(pk)
        except Sortie.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            sortie = _service.valider(sortie, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(sortie).data)

    @extend_schema(
        tags=TAG,
        summary="Annuler une sortie validée",
        description=(
            "Réservé à l'**ADMIN** (Jalon 6 — opération sensible sur un document déjà "
            "répercuté sur le stock réel). Motif obligatoire. Toutes les unités "
            "reviennent `EN_STOCK` ; rien n'est supprimé."
        ),
        request=AnnulerSortieSerializer,
    )
    @action(detail=True, methods=["post"])
    def annuler(self, request, pk=None):
        try:
            sortie = _service.obtenir(pk)
        except Sortie.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = AnnulerSortieSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            sortie = _service.annuler(sortie, serializer.validated_data["motif"], request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(sortie).data)

    @extend_schema(
        tags=TAG,
        summary="Bon de sortie (PDF)",
        description="Disponible uniquement une fois la sortie `VALIDEE`.",
        request=None,
        responses={200: OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path="bon-de-sortie.pdf")
    def bon_de_sortie(self, request, pk=None):
        try:
            sortie = _service.obtenir(pk)
        except Sortie.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if sortie.statut != StatutSortie.VALIDEE:
            return Response(
                {"detail": ["Le bon de sortie n'est disponible qu'une fois la sortie validée."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        buffer = generer_bon_de_sortie_pdf(sortie, _service.lister_lignes(sortie))
        return FileResponse(
            buffer, as_attachment=True, filename=f"{sortie.reference}.pdf", content_type="application/pdf",
        )

    @extend_schema(
        tags=TAG,
        summary="Exporter les sorties en CSV",
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
            ("Référence", lambda s: s.reference),
            ("Client", lambda s: s.client.nom),
            ("Projet", lambda s: s.projet),
            ("TRD", lambda s: s.trd),
            ("Date de sortie", lambda s: s.date_sortie),
            ("Statut", lambda s: s.get_statut_display()),
            ("Unités", lambda s: s.nb_unites),
        ]
        return exporter_csv(queryset, colonnes, "sorties")


class LigneSortieDetailView(APIView):
    """Seule route réellement imbriquée du projet (sous-ressource avec son
    propre identifiant) — ne rentre pas dans un SimpleRouter/@action."""

    permission_classes = [IsMagasinierOrReadOnly]

    @extend_schema(
        tags=TAG,
        summary="Retirer une unité d'une sortie",
        description="Réservé à MAGASINIER/ADMIN, uniquement tant que la sortie est `BROUILLON`.",
        request=None,
        responses={204: None},
    )
    def delete(self, request, sortie_id, ligne_id):
        try:
            sortie = _service.obtenir(sortie_id)
        except Sortie.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        def executer():
            _service.retirer_ligne(sortie, ligne_id, request.user)
            return status.HTTP_204_NO_CONTENT, {}

        try:
            statut_code, _ = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except LigneSortie.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=statut_code)


class ProjetAutocompleteView(APIView):
    """Libellés de projets distincts déjà utilisés — autocomplétion du champ
    texte libre `projet` à la création d'une sortie (pas de référentiel dédié,
    voir §04/§06 du dossier de conception)."""

    permission_classes = [IsAuthenticated | IsEmpotageService]

    @extend_schema(
        tags=TAG,
        summary="Autocomplétion des projets",
        parameters=[OpenApiParameter("q", OpenApiTypes.STR, description="Sous-chaîne recherchée (optionnelle).")],
        responses={200: OpenApiTypes.STR},
    )
    def get(self, request):
        q = request.query_params.get("q", "").strip()
        queryset = Sortie.objects.order_by("projet").values_list("projet", flat=True).distinct()
        if q:
            queryset = queryset.filter(projet__icontains=q)
        return Response(list(queryset[:20]))
