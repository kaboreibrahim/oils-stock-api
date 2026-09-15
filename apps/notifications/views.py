"""
=============================================================================
 apps/notifications/views.py
 ViewSet fin : chaque action délègue à NotificationService et ne fait que
 valider le format / traduire les erreurs. Tout est scopé à request.user.
=============================================================================
"""

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from .models import Notification
from .permissions import IsAuthenticated
from .serializers import AbonnementPushSerializer, NotificationSerializer
from .services import NotificationService

TAG = ["Notifications"]

_service = NotificationService()


@extend_schema_view(
    list=extend_schema(
        tags=TAG,
        summary="Lister mes notifications",
        description="Notifications du compte courant, plus récentes d'abord. Filtre : `lu` (`?lu=false`).",
    ),
)
class NotificationViewSet(GenericViewSet):
    """Notifications in-app + gestion des abonnements web push. Chaque compte
    ne voit et ne modifie que ce qui lui appartient."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["lu"]
    ordering_fields = ["created_at"]

    def get_queryset(self):
        return _service.lister(self.request.user)

    def list(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(tags=TAG, summary="Nombre de notifications non lues", request=None)
    @action(detail=False, methods=["get"], url_path="non-lus")
    def non_lus(self, request):
        return Response({"count": _service.compter_non_lus(request.user)})

    @extend_schema(tags=TAG, summary="Marquer une notification comme lue", request=None)
    @action(detail=True, methods=["post"], url_path="marquer-lu")
    def marquer_lu(self, request, pk=None):
        try:
            notification = _service.marquer_lu(request.user, pk)
        except Notification.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(NotificationSerializer(notification).data)

    @extend_schema(tags=TAG, summary="Marquer toutes mes notifications comme lues", request=None)
    @action(detail=False, methods=["post"], url_path="marquer-tout-lu")
    def marquer_tout_lu(self, request):
        return Response({"count": _service.marquer_tout_lu(request.user)})

    @extend_schema(tags=TAG, summary="Clé publique VAPID (pour l'abonnement web push)", request=None)
    @action(detail=False, methods=["get"], url_path="cle-vapid-publique")
    def cle_vapid_publique(self, request):
        return Response({"cle": settings.VAPID_PUBLIC_KEY})

    @extend_schema(
        tags=TAG,
        methods=["POST"],
        summary="Enregistrer un abonnement web push pour cet appareil",
        request=AbonnementPushSerializer,
    )
    @extend_schema(
        tags=TAG,
        methods=["DELETE"],
        summary="Supprimer l'abonnement web push de cet appareil",
        parameters=[OpenApiParameter("endpoint", str, description="Endpoint de l'abonnement à supprimer.")],
        request=None,
    )
    @action(detail=False, methods=["post", "delete"], url_path="abonnements")
    def abonnements(self, request):
        if request.method == "POST":
            serializer = AbonnementPushSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            donnees = serializer.validated_data
            _service.enregistrer_abonnement(
                utilisateur=request.user,
                endpoint=donnees["endpoint"],
                p256dh=donnees["keys"]["p256dh"],
                auth=donnees["keys"]["auth"],
                user_agent=donnees.get("user_agent", ""),
            )
            return Response(status=status.HTTP_201_CREATED)

        endpoint = request.query_params.get("endpoint") or request.data.get("endpoint")
        if not endpoint:
            return Response(
                {"detail": ["Le paramètre « endpoint » est obligatoire."]}, status=status.HTTP_400_BAD_REQUEST,
            )
        _service.supprimer_abonnement(utilisateur=request.user, endpoint=endpoint)
        return Response(status=status.HTTP_204_NO_CONTENT)
