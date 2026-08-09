from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, permissions, generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import Notification
from notifications.tasks import create_notification
from .models import Circle, CircleMembership, CircleInvite
from .serializers import CircleSerializer, CircleInviteSerializer

User = get_user_model()


class IsCircleMember(permissions.BasePermission):
    """A Circle is private — only its members may view/act on it at all."""

    def has_object_permission(self, request, view, obj):
        return CircleMembership.objects.filter(user=request.user, circle=obj).exists()


class IsCircleOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return CircleMembership.objects.filter(
            user=request.user, circle=obj, role=CircleMembership.Role.OWNER
        ).exists()


class CircleViewSet(viewsets.ModelViewSet):
    """
    /api/circles/                  -> list circles I'm a member of (no public
                                       discovery — Circles are invite-only)
                                       + create a new Circle (any user)
    /api/circles/<id>/              -> retrieve/update/delete (members only
                                        to view, owner only to edit/delete)
    /api/circles/<id>/invite/       -> POST {user_id} — owner invites someone
    /api/circles/<id>/leave/        -> POST leave (owner must transfer or
                                        delete instead — see leave())
    /api/circles/<id>/members/      -> GET member list
    """
    serializer_class = CircleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'destroy', 'invite'):
            return [permissions.IsAuthenticated(), IsCircleOwner()]
        if self.action == 'retrieve':
            return [permissions.IsAuthenticated(), IsCircleMember()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = Circle.objects.filter(members=user).annotate(
            member_count_val=Count('members', distinct=True),
        )
        if user.is_authenticated:
            qs = qs.annotate(
                is_member_val=Exists(
                    CircleMembership.objects.filter(user=user, circle=OuterRef('pk'))
                )
            )
        return qs

    def perform_create(self, serializer):
        circle = serializer.save(created_by=self.request.user)
        CircleMembership.objects.create(
            user=self.request.user, circle=circle, role=CircleMembership.Role.OWNER
        )

    @action(detail=True, methods=['post'])
    def invite(self, request, pk=None):
        circle = self.get_object()
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'detail': 'user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        invited_user = get_object_or_404(User, pk=user_id)

        if circle.is_full:
            return Response({'detail': 'This circle is already full.'}, status=status.HTTP_400_BAD_REQUEST)
        if CircleMembership.objects.filter(user=invited_user, circle=circle).exists():
            return Response({'detail': 'That user is already a member.'}, status=status.HTTP_400_BAD_REQUEST)
        invite, created = CircleInvite.objects.get_or_create(
            circle=circle, invited_user=invited_user, status=CircleInvite.Status.PENDING,
            defaults={'invited_by': request.user},
        )
        if not created:
            return Response({'detail': 'An invite is already pending for that user.'}, status=status.HTTP_400_BAD_REQUEST)

        create_notification.delay(
            recipient_id=str(invited_user.id),
            verb=Notification.Verb.CIRCLE_INVITED,
            actor_id=str(request.user.id),
            target_id=str(circle.id),
        )
        return Response(CircleInviteSerializer(invite).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        circle = self.get_object()
        membership = CircleMembership.objects.filter(user=request.user, circle=circle).first()
        if not membership:
            return Response({'detail': 'You are not a member of this circle.'}, status=status.HTTP_400_BAD_REQUEST)
        if membership.role == CircleMembership.Role.OWNER:
            # Simplest safe MVP rule: an owner can't just walk away and
            # orphan the circle. They delete it (destroy) or hand it off
            # first — same spirit as GitHub blocking "leave" for the sole
            # admin of a repo/org.
            return Response(
                {'detail': "Owners can't leave — delete the circle instead, or transfer ownership first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership.delete()
        return Response({'status': 'left', 'member_count': circle.member_count})

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated, IsCircleMember])
    def members(self, request, pk=None):
        circle = self.get_object()
        memberships = CircleMembership.objects.filter(circle=circle).select_related('user')
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


class MyCircleInvitesView(generics.ListAPIView):
    """GET /api/circles/invites/ — pending invites waiting on *me* to respond."""
    serializer_class = CircleInviteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return CircleInvite.objects.filter(
            invited_user=self.request.user, status=CircleInvite.Status.PENDING
        ).select_related('circle', 'invited_by')


class AcceptCircleInviteView(APIView):
    """POST /api/circles/invites/<id>/accept/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        invite = get_object_or_404(
            CircleInvite, pk=pk, invited_user=request.user, status=CircleInvite.Status.PENDING
        )
        if invite.circle.is_full:
            return Response({'detail': 'This circle is now full.'}, status=status.HTTP_400_BAD_REQUEST)

        invite.status = CircleInvite.Status.ACCEPTED
        invite.responded_at = timezone.now()
        invite.save(update_fields=['status', 'responded_at'])
        CircleMembership.objects.get_or_create(user=request.user, circle=invite.circle)

        if invite.invited_by_id:
            create_notification.delay(
                recipient_id=str(invite.invited_by_id),
                verb=Notification.Verb.CIRCLE_INVITE_ACCEPTED,
                actor_id=str(request.user.id),
                target_id=str(invite.circle_id),
            )
        return Response({'status': 'accepted', 'circle_id': str(invite.circle_id)})


class DeclineCircleInviteView(APIView):
    """POST /api/circles/invites/<id>/decline/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        invite = get_object_or_404(
            CircleInvite, pk=pk, invited_user=request.user, status=CircleInvite.Status.PENDING
        )
        invite.status = CircleInvite.Status.DECLINED
        invite.responded_at = timezone.now()
        invite.save(update_fields=['status', 'responded_at'])
        return Response({'status': 'declined'})
