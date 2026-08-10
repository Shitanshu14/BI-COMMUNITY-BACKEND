from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from communities.models import Membership
from users.models import Block
from .models import Message
from .serializers import MessageSerializer, ConversationSerializer

User = get_user_model()


class MessageHistoryView(generics.ListAPIView):
    """
    GET /api/chat/<community_id>/history/  -> last messages, for loading
    chat screen before the WebSocket connection takes over live updates.
    """
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        community_id = self.kwargs['community_id']
        # Same rule as the WebSocket: only members can read chat history for
        # a community — this endpoint had no such check before.
        if not Membership.objects.filter(user=self.request.user, community_id=community_id).exists():
            raise PermissionDenied('Join this community to view its chat.')
        return Message.objects.filter(community_id=community_id).select_related('sender').order_by('-created_at')[:50]


class CircleMessageHistoryView(generics.ListAPIView):
    """
    GET /api/chat/circle/<circle_id>/history/  -> last messages in a Circle's
    chat room, for loading the screen before the WebSocket takes over live
    updates. Mirrors MessageHistoryView exactly, just scoped to Circle
    membership (see circles/models.CircleMembership) instead of Community
    Membership.
    """
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        from circles.models import CircleMembership
        circle_id = self.kwargs['circle_id']
        if not CircleMembership.objects.filter(user=self.request.user, circle_id=circle_id).exists():
            raise PermissionDenied('Join this circle to view its chat.')
        return Message.objects.filter(circle_id=circle_id).select_related('sender').order_by('-created_at')[:50]


def _blocked_either_way(a, b):
    return Block.objects.filter(blocker=a, blocked=b).exists() or Block.objects.filter(blocker=b, blocked=a).exists()


class DMHistoryView(generics.ListAPIView):
    """
    GET /api/chat/dm/<user_id>/history/ -> last 50 direct messages between
    the signed-in user and <user_id>, for loading the DM screen before the
    WebSocket takes over. Mirrors MessageHistoryView's shape/limit exactly
    so the frontend can reuse the same rendering code for both.

    Also marks any of <user_id>'s messages to me as read — opening the
    thread and reading history *is* "reading" them. (The WebSocket does the
    same on connect, for the case where the tab is already open and a new
    message arrives live — this REST path covers the initial page load.)
    """
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        other = get_object_or_404(User, pk=self.kwargs['user_id'])
        if _blocked_either_way(self.request.user, other):
            raise PermissionDenied("You can't message this user.")
        me = self.request.user
        return Message.objects.filter(
            Q(sender=me, recipient=other) | Q(sender=other, recipient=me)
        ).select_related('sender', 'recipient').order_by('-created_at')[:50]

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        Message.objects.filter(
            sender_id=self.kwargs['user_id'], recipient=request.user, read_at__isnull=True
        ).update(read_at=timezone.now())
        return response


class DMConversationsView(APIView):
    """
    GET /api/chat/dm/ -> one row per person the signed-in user has
    exchanged direct messages with, most-recent first. Powers the DM inbox
    list (left pane of the Messages page).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        me = request.user
        messages = (
            Message.objects.filter(Q(sender=me) | Q(recipient=me))
            .exclude(recipient__isnull=True)
            .select_related('sender', 'recipient')
            .order_by('-created_at')
        )

        seen = set()
        rows = []
        for m in messages:
            other = m.recipient if m.sender_id == me.id else m.sender
            if other.id in seen:
                continue
            seen.add(other.id)
            rows.append({
                'user': other,
                'last_message': m.body,
                'last_message_at': m.created_at,
                # Now backed by the real read_at column (see migration
                # adding Message.read_at) — true only when the *last*
                # message is one they sent to me and I haven't opened it.
                'unread': m.sender_id != me.id and m.read_at is None,
            })

        return Response(ConversationSerializer(rows, many=True).data)


class DMUnreadCountView(APIView):
    """
    GET /api/chat/dm/unread-count/ -> {"count": N} where N is how many
    distinct people have an unread message waiting for the signed-in user.
    Deliberately its own tiny endpoint (rather than reusing
    DMConversationsView) so the Sidebar badge can poll cheaply without
    pulling every conversation's last-message text on every check.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        count = (
            Message.objects.filter(recipient=request.user, read_at__isnull=True)
            .values('sender_id')
            .distinct()
            .count()
        )
        return Response({'count': count})


class StartDMView(APIView):
    """POST /api/chat/dm/<user_id>/start/ — validates you're allowed to DM
    this person (not yourself, not blocked either direction) before the
    frontend opens the WebSocket. Returns the target user's public profile
    so the DM screen has a name/avatar to show even with zero history."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        target = get_object_or_404(User, pk=user_id)
        if target.id == request.user.id:
            return Response({'detail': "You can't message yourself."}, status=status.HTTP_400_BAD_REQUEST)
        if _blocked_either_way(request.user, target):
            return Response({'detail': "You can't message this user."}, status=status.HTTP_400_BAD_REQUEST)
        from users.serializers import UserSerializer
        return Response(UserSerializer(target).data)
