from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.models import Message
from circles.models import Circle, CircleMembership
from communities.models import Community, Membership
from posts.models import Post
from verification.models import VerificationRequest

from .permissions import IsSupportUser
from .serializers import (
    SupportUserSerializer, SupportCommunitySerializer, SupportCircleSerializer,
    SupportCommunityMemberSerializer, SupportCircleMemberSerializer,
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


class SupportCommunityListView(generics.ListAPIView):
    """GET /api/support/communities/ — every community with a live member count."""
    permission_classes = [IsSupportUser]
    serializer_class = SupportCommunitySerializer

    def get_queryset(self):
        return Community.objects.annotate(member_count_val=Count('membership')).order_by('name')


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


class SupportCircleListView(generics.ListAPIView):
    """GET /api/support/circles/ — every circle with a live member count."""
    permission_classes = [IsSupportUser]
    serializer_class = SupportCircleSerializer

    def get_queryset(self):
        return Circle.objects.annotate(member_count_val=Count('circlemembership')).order_by('name')


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
