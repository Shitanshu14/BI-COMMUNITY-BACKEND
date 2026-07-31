from django.db.models import Q
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Community, Membership
from .serializers import CommunitySerializer


class CommunityViewSet(viewsets.ModelViewSet):
    """
    /api/communities/                 -> list + discover (search by name)
    /api/communities/<id>/             -> retrieve
    /api/communities/<id>/join/        -> POST join
    /api/communities/<id>/leave/       -> POST leave
    """
    queryset = Community.objects.all()
    serializer_class = CommunitySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def join(self, request, pk=None):
        community = self.get_object()
        Membership.objects.get_or_create(user=request.user, community=community)
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
