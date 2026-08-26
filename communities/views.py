from django.db.models import Count, Exists, OuterRef
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from notifications.models import Notification
from notifications.tasks import notify
from .models import Community, Membership
from .serializers import CommunitySerializer


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Communities are created only by admins (Django Admin login / staff users).
    Any *logged-in* user can list/view communities (read requires login —
    there's no anonymous browsing of the platform, see the login-gate
    requirement). Regular logged-in users can never create/edit/delete a
    community — they can only join/leave and post inside one.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user.is_staff)


class CommunityViewSet(viewsets.ModelViewSet):
    """
    /api/communities/                 -> list + discover (search by name)
    /api/communities/<id>/             -> retrieve
    /api/communities/<id>/join/        -> POST join
    /api/communities/<id>/leave/       -> POST leave

    Create/update/delete is admin-only (is_staff) — communities are made
    from the Django Admin panel, not by regular users through the app.
    """
    # `member_count` used to be a plain @property (self.members.count()),
    # which meant DRF fired one extra COUNT query PER community on every
    # list request (classic N+1 — 100 communities = 101 queries). Annotating
    # it here does the whole thing in a single query regardless of list size.
    #
    # The explicit .order_by() matters: Community.Meta already sets
    # ordering=['-created_at'], but annotating an aggregate (Count) forces
    # a GROUP BY, and Django doesn't reliably carry a model's default
    # ordering through that — .ordered comes back False and Django logs
    # "UnorderedObjectListWarning: pagination may yield inconsistent
    # results". In practice that meant page 2 of the community list could
    # repeat or skip communities from page 1 depending on the DB's whim.
    # Being explicit here fixes it for good regardless of what future
    # annotations get added.
    queryset = Community.objects.annotate(
        member_count_val=Count('members', distinct=True)
    ).order_by('-created_at')
    serializer_class = CommunitySerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_authenticated:
            # Same fix as is_liked on posts: one Exists() annotation instead
            # of a per-row Membership.objects.filter(...).exists() query.
            qs = qs.annotate(
                is_member_val=Exists(
                    Membership.objects.filter(user=user, community=OuterRef('pk'))
                )
            )
        return qs

    def perform_create(self, serializer):
        community = serializer.save(created_by=self.request.user)
        # Auto-join the creator as an admin member — without this a brand
        # new community always shows "0 members" even to its own creator.
        Membership.objects.get_or_create(
            user=self.request.user, community=community, defaults={'role': Membership.Role.ADMIN}
        )

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def join(self, request, pk=None):
        community = self.get_object()
        _, created = Membership.objects.get_or_create(user=request.user, community=community)
        if created and community.created_by_id:
            notify(
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
