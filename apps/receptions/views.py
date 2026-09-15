"""
=============================================================================
 apps/receptions/views.py
 ViewSet fin : valide le format (serializer), délègue tout à ReceptionService,
 traduit les erreurs métier en réponses HTTP. Même organisation que
 apps.sorties.views : @action pour lignes/valider/annuler, vue dédiée pour la
 seule sous-ressource réellement imbriquée (lignes/{id}/, suppression).
=============================================================================
"""

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from drf_spectacular.utils import OpenApiExample, OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.common.exports import exporter_csv
from apps.common.idempotence import executer_avec_idempotence

from .filters import ReceptionFilter
from .models import LigneReception, Reception
from .permissions import IsAdmin, IsMagasinierOrReadOnly
from .serializers import (
    AjouterLigneReceptionSerializer,
    AjouterPlageReceptionSerializer,
    AnnulerReceptionSerializer,
    ExtraireSerializer,
    ExtractionResultatSerializer,
    LigneReceptionSerializer,
    ReceptionDetailSerializer,
    ReceptionSerializer,
)
from .services import ReceptionService

TAG = ["Réceptions"]

_service = ReceptionService()


@extend_schema_view(
    list=extend_schema(
        tags=TAG,
        summary="Lister les réceptions",
        description=(
            "Ouvert à tous les rôles. Filtres : `nature` (`ARRIVAGE`/`SAISIE`/`REPRISE`), "
            "`statut`, `fournisseur`, `date_debut`, `date_fin` · recherche : `reference`, `reference_fournisseur`."
        ),
    ),
    retrieve=extend_schema(
        tags=TAG, summary="Détail d'une réception", description="Inclut les lignes de la réception.",
    ),
    create=extend_schema(
        tags=TAG,
        summary="Créer une réception (brouillon)",
        examples=[
            OpenApiExample(
                "Saisie manuelle",
                value={
                    "nature": "SAISIE", "fournisseur": "3b1b7e2e-2222-4444-8888-000000000001",
                    "date_reception": "2026-09-10", "quantite_annoncee": 26,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Reprise de l'existant",
                value={"nature": "REPRISE", "date_reception": "2026-09-10"},
                request_only=True,
            ),
        ],
        description=(
            "Réservé à **MAGASINIER**/**ADMIN** pour `SAISIE`/`ARRIVAGE` ; **ADMIN uniquement** "
            "pour `REPRISE` (§09 du dossier de conception). Naît au statut `BROUILLON`, référence "
            "générée automatiquement. `ARRIVAGE` exige `fichier` (PDF, multipart) — voir `/extraire/`."
        ),
    ),
    update=extend_schema(tags=TAG, summary="Modifier l'en-tête d'une réception", description="Uniquement tant que `BROUILLON`."),
    partial_update=extend_schema(tags=TAG, summary="Modifier partiellement l'en-tête", description="Uniquement tant que `BROUILLON`."),
    destroy=extend_schema(
        tags=TAG, summary="Supprimer une réception brouillon", description="Suppression logique, uniquement tant que `BROUILLON`.",
    ),
)
class ReceptionViewSet(GenericViewSet):
    """Lecture pour tous ; écriture pour magasinier et admin (reprise : admin seul). Tout passe par ReceptionService."""

    permission_classes = [IsMagasinierOrReadOnly]
    filterset_class = ReceptionFilter
    search_fields = ["reference", "reference_fournisseur"]
    ordering_fields = ["date_reception", "created_at", "reference"]

    def get_permissions(self):
        # Annuler une réception déjà validée est réservé à l'admin (Jalon 6 —
        # §09, note * tranchée), même raisonnement que pour les sorties.
        if self.action == "annuler":
            return [IsAdmin()]
        return super().get_permissions()

    def get_queryset(self):
        return _service.lister()

    def get_serializer_class(self):
        if self.action in {"retrieve", "valider", "annuler"}:
            return ReceptionDetailSerializer
        return ReceptionSerializer

    def list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            reception = _service.obtenir(pk)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(reception).data)

    def create(self, request):
        def executer():
            # Validation à l'intérieur : un rejeu ne doit jamais revalider —
            # voir apps.sorties.views.SortieViewSet.create pour le détail.
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            reception = _service.creer(serializer.validated_data, request.user)
            return status.HTTP_201_CREATED, self.get_serializer(reception).data

        try:
            statut_code, corps = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except PermissionDenied as exc:
            return Response({"detail": [str(exc)]}, status=status.HTTP_403_FORBIDDEN)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(corps, status=statut_code)

    def update(self, request, pk=None, partial=False):
        try:
            reception = _service.obtenir(pk)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(reception, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            reception = _service.modifier(reception, serializer.validated_data, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(reception).data)

    def partial_update(self, request, pk=None):
        return self.update(request, pk=pk, partial=True)

    def destroy(self, request, pk=None):
        try:
            reception = _service.obtenir(pk)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            _service.supprimer(reception, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=TAG,
        summary="Télécharger le PDF d'arrivage",
        description=(
            "Sert le fichier via l'API plutôt que l'URL média brute (même raison que le bon "
            "de sortie des sorties, §Jalon 2) : authentification JWT cohérente, et évite tout "
            "souci CORS quand le frontend et l'API ne sont pas sur le même hôte (ex. tunnel)."
        ),
        request=None,
        responses={200: OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"])
    def fichier(self, request, pk=None):
        try:
            reception = _service.obtenir(pk)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not reception.fichier:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return FileResponse(
            reception.fichier.open("rb"), content_type="application/pdf",
            filename=f"{reception.reference}.pdf",
        )

    # ── Lignes ───────────────────────────────────────────────────────────

    @extend_schema(tags=TAG, methods=["GET"], summary="Lister les unités d'une réception")
    @extend_schema(
        tags=TAG,
        methods=["POST"],
        summary="Ajouter une unité à une réception",
        description=(
            "Réservé à MAGASINIER/ADMIN, uniquement tant que `BROUILLON`. Marquée `DOUBLON` "
            "si déjà en stock ou déjà présente sur cette réception (ne bloque pas l'ajout, "
            "bloque juste la validation tant que la ligne n'est pas retirée/corrigée)."
        ),
        request=AjouterLigneReceptionSerializer,
        examples=[OpenApiExample("Requête", value={"numero_serie": "008647", "type_article": "HEATING_PAD"}, request_only=True)],
    )
    @action(detail=True, methods=["get", "post"], url_path="lignes")
    def lignes(self, request, pk=None):
        try:
            reception = _service.obtenir(pk)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if request.method == "GET":
            queryset = _service.lister_lignes(reception)
            return Response(LigneReceptionSerializer(queryset, many=True).data)

        def executer():
            serializer = AjouterLigneReceptionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            donnees = serializer.validated_data
            ligne = _service.ajouter_ligne(
                reception,
                numero_serie=donnees["numero_serie"], type_article=donnees["type_article"],
                utilisateur=request.user, fournisseur_id=donnees.get("fournisseur"),
                fournisseur_code=donnees.get("fournisseur_code"),
            )
            return status.HTTP_201_CREATED, LigneReceptionSerializer(ligne).data

        try:
            statut_code, corps = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(corps, status=statut_code)

    @extend_schema(
        tags=TAG,
        summary="Générer une plage de numéros de série",
        description=(
            "Réservé à MAGASINIER/ADMIN, uniquement tant que `BROUILLON`. Génère une ligne par "
            "numéro entre `debut` et `fin` (préfixe commun, compteur zéro-préfixé sur `largeur` "
            "chiffres) — utile pour un lot séquentiel (ex. Ebont, `24E3231260424A001`…`A131`)."
        ),
        request=AjouterPlageReceptionSerializer,
        examples=[
            OpenApiExample(
                "Requête",
                value={"prefixe": "24E3231260424A", "debut": 1, "fin": 131, "largeur": 3, "type_article": "FLEXITANK"},
                request_only=True,
            ),
        ],
    )
    @action(detail=True, methods=["post"], url_path="lignes/plage")
    def plage(self, request, pk=None):
        try:
            reception = _service.obtenir(pk)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        def executer():
            serializer = AjouterPlageReceptionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            donnees = serializer.validated_data
            lignes = _service.ajouter_plage(
                reception,
                prefixe=donnees["prefixe"], debut=donnees["debut"], fin=donnees["fin"],
                largeur=donnees.get("largeur"), type_article=donnees["type_article"],
                utilisateur=request.user, fournisseur_id=donnees.get("fournisseur"),
                fournisseur_code=donnees.get("fournisseur_code"),
            )
            return status.HTTP_201_CREATED, LigneReceptionSerializer(lignes, many=True).data

        try:
            statut_code, corps = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(corps, status=statut_code)

    @extend_schema(
        tags=TAG,
        summary="(Re)lancer l'extraction du PDF",
        description=(
            "Réservé à MAGASINIER/ADMIN, uniquement pour un `ARRIVAGE` `BROUILLON` avec fichier. "
            "Relit le PDF (pdfplumber) selon le profil d'extraction du fournisseur "
            "(`/fournisseurs/{id}/profil-extraction/`), ou une détection générique sinon "
            "(lignes marquées `A_VERIFIER`). Une page sans couche texte (PDF scanné) passe "
            "par l'OCR (Tesseract) — mêmes lignes marquées `A_VERIFIER`, confiance moindre. "
            "Un nouvel appel ne touche qu'aux lignes issues d'une extraction précédente — les "
            "lignes ajoutées/corrigées à la main sont conservées."
        ),
        request=ExtraireSerializer,
        responses={200: ExtractionResultatSerializer},
        examples=[OpenApiExample("Requête", value={"type_article": "FLEXITANK"}, request_only=True)],
    )
    @action(detail=True, methods=["post"])
    def extraire(self, request, pk=None):
        try:
            reception = _service.obtenir(pk)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = ExtraireSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            resultat = _service.extraire(
                reception, request.user, type_article=serializer.validated_data.get("type_article"),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExtractionResultatSerializer({
            "lignes": resultat["lignes"],
            "plage_detectee": resultat["plage_detectee"],
            "generique": resultat["generique"],
            "ocr_utilise": resultat["ocr_utilise"],
        }).data)

    # ── Cycle de vie ─────────────────────────────────────────────────────

    @extend_schema(
        tags=TAG,
        summary="Valider une réception",
        description=(
            "Chaque ligne `OK` devient une `UniteStock` `EN_STOCK` + un mouvement `ENTREE`. "
            "Refusé si une ligne n'est pas `OK` (doublon à résoudre d'abord)."
        ),
        request=None,
    )
    @action(detail=True, methods=["post"])
    def valider(self, request, pk=None):
        try:
            reception = _service.obtenir(pk)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            reception = _service.valider(reception, request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(reception).data)

    @extend_schema(
        tags=TAG,
        summary="Annuler une réception validée",
        description=(
            "Réservé à l'**ADMIN** (Jalon 6 — opération sensible sur un document déjà "
            "répercuté sur le stock réel). Motif obligatoire. Les unités créées par cette "
            "réception sont retirées (suppression logique) — refusé si l'une d'elles n'est "
            "plus en stock (déjà sortie)."
        ),
        request=AnnulerReceptionSerializer,
    )
    @action(detail=True, methods=["post"])
    def annuler(self, request, pk=None):
        try:
            reception = _service.obtenir(pk)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = AnnulerReceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reception = _service.annuler(reception, serializer.validated_data["motif"], request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(reception).data)

    @extend_schema(
        tags=TAG,
        summary="Exporter les réceptions en CSV",
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
            ("Référence", lambda r: r.reference),
            ("Nature", lambda r: r.get_nature_display()),
            ("Fournisseur", lambda r: r.fournisseur.code if r.fournisseur else None),
            ("Référence fournisseur", lambda r: r.reference_fournisseur),
            ("Date de réception", lambda r: r.date_reception),
            ("Statut", lambda r: r.get_statut_display()),
            ("Lignes", lambda r: r.nb_lignes),
        ]
        return exporter_csv(queryset, colonnes, "receptions")


class LigneReceptionDetailView(APIView):
    """Seule sous-ressource réellement imbriquée avec son propre identifiant
    (comme `apps.sorties.LigneSortieDetailView`) — ne rentre pas dans un
    SimpleRouter/@action."""

    permission_classes = [IsMagasinierOrReadOnly]

    @extend_schema(
        tags=TAG,
        summary="Retirer une unité d'une réception",
        description="Réservé à MAGASINIER/ADMIN, uniquement tant que la réception est `BROUILLON`.",
        request=None,
        responses={204: None},
    )
    def delete(self, request, reception_id, ligne_id):
        try:
            reception = _service.obtenir(reception_id)
        except Reception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        def executer():
            _service.retirer_ligne(reception, ligne_id, request.user)
            return status.HTTP_204_NO_CONTENT, {}

        try:
            statut_code, _ = executer_avec_idempotence(
                request, request.headers.get("Idempotency-Key"), executer,
            )
        except LigneReception.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=statut_code)
