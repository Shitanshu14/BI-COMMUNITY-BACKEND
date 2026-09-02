from django.db.models import Count, Exists, ExpressionWrapper, F, IntegerField, OuterRef, Q
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from notifications.models import Notification
from notifications.tasks import notify
from .models import Community, Membership
from .serializers import CommunitySerializer


def _is_community_admin(user, community):
    if not (user and user.is_authenticated):
        return False
    if user.is_staff:
        return True
    return Membership.objects.filter(
        user=user, community=community, status=Membership.Status.APPROVED, role=Membership.Role.ADMIN
    ).exists()


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Communities are created only by admins (Django Admin login / staff
    users) — regular users build Circles instead (see circles/views.py),
    not Communities. Any *logged-in* user can list/view communities (read
    requires login — there's no anonymous browsing of the platform, see
    the login-gate requirement). Editing/deleting stays staff or that
    community's own admins, checked at the object level below.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if view.action == 'create':
            return bool(request.user.is_staff)
        return True  # narrowed per-object in has_object_permission

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return _is_community_admin(request.user, obj)


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
        # Only APPROVED memberships count as real members — someone with a
        # pending registration request on an approval-based community
        # hasn't joined yet (see Membership.Status). The vanity
        # `member_count_boost` is added on top, same as the model property,
        # so list/retrieve responses match what Membership-based lookups
        # would give.
        _approved_count=Count(
            'membership', filter=Q(membership__status=Membership.Status.APPROVED), distinct=True
        )
    ).annotate(
        member_count_val=ExpressionWrapper(
            F('_approved_count') + F('member_count_boost'), output_field=IntegerField()
        )
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
                    Membership.objects.filter(
                        user=user, community=OuterRef('pk'), status=Membership.Status.APPROVED
                    )
                ),
                is_pending_val=Exists(
                    Membership.objects.filter(
                        user=user, community=OuterRef('pk'), status=Membership.Status.PENDING
                    )
                ),
            )
        return qs

    def perform_create(self, serializer):
        community = serializer.save(created_by=self.request.user)
        # Auto-join the creator as an approved admin member — without this
        # a brand new community always shows "0 members" even to its own
        # creator, and they'd have no way to manage it (approve join
        # requests, moderate) since they wouldn't be a member at all.
        Membership.objects.get_or_create(
            user=self.request.user, community=community,
            defaults={'role': Membership.Role.ADMIN, 'status': Membership.Status.APPROVED},
        )

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def join(self, request, pk=None):
        community = self.get_object()
        existing = Membership.objects.filter(user=request.user, community=community).first()
        if existing and existing.status == Membership.Status.APPROVED:
            return Response({'status': 'joined', 'member_count': community.member_count})
        if existing and existing.status == Membership.Status.PENDING:
            return Response({'status': 'pending', 'member_count': community.member_count})

        # Registration-based ("approval") communities don't grant
        # membership on tap — the request sits pending until a community
        # admin approves it. Open communities keep the original one-tap
        # join behaviour.
        if community.join_mode == Community.JoinMode.APPROVAL:
            Membership.objects.create(user=request.user, community=community, status=Membership.Status.PENDING)
            for admin_id in Membership.objects.filter(
                community=community, role=Membership.Role.ADMIN, status=Membership.Status.APPROVED
            ).values_list('user_id', flat=True):
                notify(
                    recipient_id=str(admin_id),
                    verb=Notification.Verb.COMMUNITY_JOINED,
                    actor_id=str(request.user.id),
                    target_id=str(community.id),
                )
            return Response({'status': 'pending', 'member_count': community.member_count})

        Membership.objects.create(user=request.user, community=community, status=Membership.Status.APPROVED)
        if community.created_by_id:
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
        # Also cancels a still-pending registration request, so "Leave" /
        # "Cancel request" is the same action from the member's side.
        Membership.objects.filter(user=request.user, community=community).delete()
        return Response({'status': 'left', 'member_count': community.member_count})

    @action(detail=True, methods=['get'])
    def members(self, request, pk=None):
        community = self.get_object()
        # Private communities are fully locked to non-members: no posts, no
        # chat, and no peeking at who's inside either. Open communities keep
        # showing their member list to anyone logged in (normal "who's in
        # this group" discovery).
        if not community.is_public and not _is_community_admin(request.user, community) and not (
            Membership.objects.filter(
                user=request.user, community=community, status=Membership.Status.APPROVED
            ).exists()
        ):
            return Response({'detail': 'This is a private community — join to see its members.'}, status=403)
        memberships = Membership.objects.filter(
            community=community, status=Membership.Status.APPROVED
        ).select_related('user')
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

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def join_requests(self, request, pk=None):
        """Pending registration requests for a join_mode=approval community
        — admins/moderators only, so a random member can't see who else
        is waiting or approve people in."""
        community = self.get_object()
        if not _is_community_admin(request.user, community):
            return Response({'detail': 'Only community admins can view join requests.'}, status=403)
        memberships = Membership.objects.filter(
            community=community, status=Membership.Status.PENDING
        ).select_related('user').order_by('joined_at')
        data = [
            {
                'membership_id': m.id,
                'id': m.user.id,
                'username': m.user.username,
                'headline': m.user.headline,
                'requested_at': m.joined_at,
            }
            for m in memberships
        ]
        return Response(data)

    @action(detail=True, methods=['post'], url_path='join_requests/(?P<user_id>[^/.]+)/approve',
            permission_classes=[permissions.IsAuthenticated])
    def approve_join_request(self, request, pk=None, user_id=None):
        community = self.get_object()
        if not _is_community_admin(request.user, community):
            return Response({'detail': 'Only community admins can approve join requests.'}, status=403)
        membership = Membership.objects.filter(
            community=community, user_id=user_id, status=Membership.Status.PENDING
        ).first()
        if not membership:
            return Response({'detail': 'No pending request for this user.'}, status=404)
        membership.status = Membership.Status.APPROVED
        membership.save(update_fields=['status'])
        notify(
            recipient_id=str(user_id),
            verb=Notification.Verb.COMMUNITY_JOINED,
            actor_id=str(request.user.id),
            target_id=str(community.id),
        )
        return Response({'status': 'approved', 'member_count': community.member_count})

    @action(detail=True, methods=['post'], url_path='join_requests/(?P<user_id>[^/.]+)/reject',
            permission_classes=[permissions.IsAuthenticated])
    def reject_join_request(self, request, pk=None, user_id=None):
        community = self.get_object()
        if not _is_community_admin(request.user, community):
            return Response({'detail': 'Only community admins can reject join requests.'}, status=403)
        deleted, _ = Membership.objects.filter(
            community=community, user_id=user_id, status=Membership.Status.PENDING
        ).delete()
        if not deleted:
            return Response({'detail': 'No pending request for this user.'}, status=404)
        return Response({'status': 'rejected'})
