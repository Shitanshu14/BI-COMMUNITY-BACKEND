from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from chat.models import Message
from circles.models import Circle, CircleMembership
from communities.models import Community, Membership
from communities.serializers import CommunitySerializer
from circles.serializers import CircleSerializer
from posts.models import Post
from verification.models import VerificationRequest

from .models import SupportTicket
from .permissions import IsSupportUser
from .serializers import (
    SupportUserSerializer,
    SupportCommunitySerializer, SupportCircleSerializer,
    SupportCommunityMemberSerializer, SupportCircleMemberSerializer,
    SupportTicketSerializer,
)

User = get_user_model()


class SupportStatsView(APIView):
    """
    GET /api/support/stats/ — the 6 headline numbers on the dashboard.
    One view, one round trip, rather than the frontend firing 6 separate
    count requests on load.
    """
    permission_classes = [IsSupportUser]

    def get(self, request):
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return Response({
            'total_users': User.objects.count(),
            'active_users': User.objects.filter(is_active=True).count(),
            'total_communities': Community.objects.count(),
            'total_circles': Circle.objects.count(),
            'total_posts': Post.objects.count(),
            'messages_today': Message.objects.filter(created_at__gte=today_start).count(),
            'pending_verifications': VerificationRequest.objects.filter(status='pending').count(),
            'blocked_users': User.objects.filter(is_active=False).count(),
        })


class SupportUserListView(generics.ListAPIView):
    """
    GET /api/support/users/?q=<search>&status=all|active|blocked
    Every user, searchable by username/email, with per-user
    community/circle/post counts annotated in a single query each (not
    one query per row — see SupportUserSerializer docstring).
    """
    permission_classes = [IsSupportUser]
    serializer_class = SupportUserSerializer

    def get_queryset(self):
        qs = User.objects.annotate(
            community_count=Count('membership', distinct=True),
            circle_count=Count('circlemembership', distinct=True),
            post_count=Count('posts', distinct=True),
        ).order_by('-created_at')

        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q))

        status_filter = self.request.query_params.get('status')
        if status_filter == 'active':
            qs = qs.filter(is_active=True)
        elif status_filter == 'blocked':
            qs = qs.filter(is_active=False)

        return qs


class SupportUserToggleActiveView(APIView):
    """
    POST /api/support/users/<id>/toggle-active/ — block (deactivate) or
    unblock (reactivate) an account. This is the same `is_active` flag
    the login view already checks, so a blocked user is immediately
    locked out — no separate "ban" concept to keep in sync.
    """
    permission_classes = [IsSupportUser]

    def post(self, request, pk):
        target = generics.get_object_or_404(User, pk=pk)

        if target.id == request.user.id:
            return Response({'detail': "You can't block your own account."}, status=status.HTTP_400_BAD_REQUEST)
        if target.is_staff and not request.user.is_staff:
            # A support user (not full staff) shouldn't be able to lock out
            # a real admin — only another is_staff account can do that.
            return Response({'detail': 'Only a staff admin can block another staff account.'}, status=status.HTTP_403_FORBIDDEN)

        target.is_active = not target.is_active
        target.save(update_fields=['is_active'])
        return Response(SupportUserSerializer(target).data)


class SupportUserDetailView(APIView):
    """
    GET /api/support/users/<id>/ — full profile for the detail panel: the
    list row only has counts, this has the actual community/circle names
    (clicking a user in the dashboard needs somewhere to land).
    """
    permission_classes = [IsSupportUser]

    def get(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        base = SupportUserSerializer(
            User.objects.annotate(
                community_count=Count('membership', distinct=True),
                circle_count=Count('circlemembership', distinct=True),
                post_count=Count('posts', distinct=True),
            ).get(pk=pk)
        ).data
        base['bio'] = target.bio
        base['headline'] = target.headline
        base['communities'] = [
            {'id': m.community_id, 'name': m.community.name, 'role': m.role, 'joined_at': m.joined_at}
            for m in Membership.objects.filter(user=target).select_related('community')
        ]
        base['circles'] = [
            {'id': m.circle_id, 'name': m.circle.name, 'role': m.role, 'joined_at': m.joined_at}
            for m in CircleMembership.objects.filter(user=target).select_related('circle')
        ]
        return Response(base)


class SupportCommunityListView(generics.ListCreateAPIView):
    """
    GET  /api/support/communities/ — every community with a live member count.
    POST /api/support/communities/ — create one.

    The main POST /api/communities/ endpoint is gated to is_staff (see
    communities/views.py IsAdminOrReadOnly) — a support user who isn't
    also is_staff couldn't create a community there, so this gives the
    dashboard its own creation path under IsSupportUser instead.
    """
    permission_classes = [IsSupportUser]
    serializer_class = SupportCommunitySerializer

    def get_queryset(self):
        return Community.objects.annotate(member_count_val=Count('membership')).order_by('name')

    def get_serializer_class(self):
        # Reuse the real CommunitySerializer for writes — it already
        # handles slug auto-generation from `name` (see its docstring).
        # SupportCommunitySerializer is read-only (member_count is a
        # SerializerMethodField), so it can't validate/save a POST body.
        if self.request.method == 'POST':
            return CommunitySerializer
        return SupportCommunitySerializer

    def perform_create(self, serializer):
        community = serializer.save(created_by=self.request.user)
        # Same as the main community creation flow — auto-join the creator
        # as admin so it doesn't show 0 members immediately, and so
        # whoever made it (the support user) can manage it normally too.
        Membership.objects.get_or_create(
            user=self.request.user, community=community, defaults={'role': Membership.Role.ADMIN}
        )

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        # The write serializer (CommunitySerializer) doesn't include
        # member_count_val — re-serialize with the read serializer so the
        # response matches what the list view returns (the frontend adds
        # this straight into its local list state).
        community = Community.objects.annotate(member_count_val=Count('membership')).get(pk=response.data['id'])
        response.data = SupportCommunitySerializer(community).data
        return response


class SupportCommunityDetailView(generics.DestroyAPIView):
    """DELETE /api/support/communities/<id>/ — remove a community entirely."""
    permission_classes = [IsSupportUser]
    queryset = Community.objects.all()


class SupportCommunityMemberRemoveView(APIView):
    """DELETE /api/support/communities/<id>/members/<user_id>/ — kick a member out."""
    permission_classes = [IsSupportUser]

    def delete(self, request, pk, user_id):
        deleted, _ = Membership.objects.filter(community_id=pk, user_id=user_id).delete()
        if not deleted:
            return Response({'detail': 'That user is not a member of this community.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SupportCommunityMembersView(generics.ListAPIView):
    """GET /api/support/communities/<id>/members/ — who's in this community."""
    permission_classes = [IsSupportUser]
    serializer_class = SupportCommunityMemberSerializer

    def get_queryset(self):
        return (
            Membership.objects.filter(community_id=self.kwargs['pk'])
            .select_related('user')
            .order_by('-joined_at')
        )


class SupportCircleListView(generics.ListCreateAPIView):
    """
    GET  /api/support/circles/ — every circle with a live member count.
    POST /api/support/circles/ — create one.

    Unlike communities, any authenticated user (including a support
    account) can already create a circle via POST /api/circles/ — see
    circles/models.py Circle docstring. This exists mainly for symmetry
    with the community create flow above and so the dashboard doesn't
    need two different endpoints for "create a group".
    """
    permission_classes = [IsSupportUser]
    serializer_class = SupportCircleSerializer

    def get_queryset(self):
        return Circle.objects.annotate(member_count_val=Count('circlemembership')).order_by('name')

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CircleSerializer
        return SupportCircleSerializer

    def perform_create(self, serializer):
        circle = serializer.save(created_by=self.request.user)
        CircleMembership.objects.get_or_create(
            user=self.request.user, circle=circle, defaults={'role': CircleMembership.Role.OWNER}
        )

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        circle = Circle.objects.annotate(member_count_val=Count('circlemembership')).get(pk=response.data['id'])
        response.data = SupportCircleSerializer(circle).data
        return response


class SupportCircleDetailView(generics.DestroyAPIView):
    """DELETE /api/support/circles/<id>/ — remove a circle entirely."""
    permission_classes = [IsSupportUser]
    queryset = Circle.objects.all()


class SupportCommunityToggleHoldView(APIView):
    """
    POST /api/support/communities/<id>/toggle-hold/ — freeze or unfreeze a
    community (see Community.is_on_hold docstring). Doesn't touch
    membership or existing content, just the write paths in
    posts/views.py (ensure_not_on_hold).
    """
    permission_classes = [IsSupportUser]

    def post(self, request, pk):
        community = get_object_or_404(Community, pk=pk)
        community.is_on_hold = not community.is_on_hold
        community.save(update_fields=['is_on_hold'])
        return Response(SupportCommunitySerializer(
            Community.objects.annotate(member_count_val=Count('membership')).get(pk=pk)
        ).data)


class SupportPostDeleteView(generics.DestroyAPIView):
    """
    DELETE /api/support/posts/<id>/ — moderation removal. Separate from
    the normal PostViewSet.destroy (which only the post's own author can
    hit) rather than loosening that permission — a support account
    deleting someone else's post is a distinct, audited-by-being-a-
    different-endpoint action, not "posts can be deleted by anyone with
    IsSupportUser" bolted onto the regular API surface.
    """
    permission_classes = [IsSupportUser]
    queryset = Post.objects.all()


class SupportTicketCreateView(generics.CreateAPIView):
    """
    POST /api/support/tickets/create/ — the public "Contact support" form.
    Deliberately AllowAny: the two people most likely to need this are a
    blocked user (can't log in by definition) and someone whose password
    reset isn't arriving — both are logged out. If the request comes from
    someone who *is* authenticated, attach their account automatically so
    support doesn't have to go search for it.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = SupportTicketSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'support_ticket'

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(user=user)


class SupportTicketListView(generics.ListAPIView):
    """GET /api/support/tickets/?status=open|resolved — the queue support triages."""
    permission_classes = [IsSupportUser]
    serializer_class = SupportTicketSerializer

    def get_queryset(self):
        qs = SupportTicket.objects.all()
        status_filter = self.request.query_params.get('status')
        if status_filter in (SupportTicket.Status.OPEN, SupportTicket.Status.RESOLVED):
            qs = qs.filter(status=status_filter)
        return qs


class SupportTicketResolveView(APIView):
    """POST /api/support/tickets/<id>/resolve/ — mark handled (toggles back to open if called again)."""
    permission_classes = [IsSupportUser]

    def post(self, request, pk):
        ticket = get_object_or_404(SupportTicket, pk=pk)
        if ticket.status == SupportTicket.Status.OPEN:
            ticket.status = SupportTicket.Status.RESOLVED
            ticket.resolved_at = timezone.now()
        else:
            ticket.status = SupportTicket.Status.OPEN
            ticket.resolved_at = None
        ticket.save(update_fields=['status', 'resolved_at'])
        return Response(SupportTicketSerializer(ticket).data)


class SupportCircleMembersView(generics.ListAPIView):
    """GET /api/support/circles/<id>/members/ — who's in this circle."""
    permission_classes = [IsSupportUser]
    serializer_class = SupportCircleMemberSerializer

    def get_queryset(self):
        return (
            CircleMembership.objects.filter(circle_id=self.kwargs['pk'])
            .select_related('user')
            .order_by('-joined_at')
        )


class SupportCircleMemberRemoveView(APIView):
    """DELETE /api/support/circles/<id>/members/<user_id>/ — kick a member out."""
    permission_classes = [IsSupportUser]

    def delete(self, request, pk, user_id):
        deleted, _ = CircleMembership.objects.filter(circle_id=pk, user_id=user_id).delete()
        if not deleted:
            return Response({'detail': 'That user is not a member of this circle.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
