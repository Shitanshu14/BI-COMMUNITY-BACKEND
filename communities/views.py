from django.db.models import Q
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from notifications.models import Notification
from notifications.tasks import create_notification
from .models import Community, Membership
from .serializers import CommunitySerializer


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Communities are created only by admins (Django Admin login / staff users).
    Everyone (including anonymous, read-only) can list/view communities.
    Regular logged-in users can never create/edit/delete a community — they
    can only join/leave and post inside one.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class CommunityViewSet(viewsets.ModelViewSet):
    """
    /api/communities/                 -> list + discover (search by name)
    /api/communities/<id>/             -> retrieve
    /api/communities/<id>/join/        -> POST join
    /api/communities/<id>/leave/       -> POST leave

    Create/update/delete is admin-only (is_staff) — communities are made
    from the Django Admin panel, not by regular users through the app.
    """
    queryset = Community.objects.all()
    serializer_class = CommunitySerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def join(self, request, pk=None):
        community = self.get_object()
        _, created = Membership.objects.get_or_create(user=request.user, community=community)
        if created and community.created_by_id:
            create_notification.delay(
                recipient_id=str(community.created_by_id),
                verb=Notification.Verb.COMMUNITY_JOINED,
                actor_id=str(request.user.id),
                target_id=str(community.id),
            )
        return Response({'status': 'joined', 'member_count': community.member_count})

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def leave(self, request, pk=None):
        community = self.get_object()
        Membership.objects.filter(user=request.user, community=community).delete()
        return Response({'status': 'left', 'member_count': community.member_count})

    @action(detail=True, methods=['get'])
    def members(self, request, pk=None):
        community = self.get_object()
        memberships = Membership.objects.filter(community=community).select_related('user')
        data = [
            {
                'id': m.user.id,
                'username': m.user.username,
                'headline': m.user.headline,
                'role': m.role,
                'is_verified': m.user.is_verified,
            }
            for m in memberships
        ]
        return Response(data)
