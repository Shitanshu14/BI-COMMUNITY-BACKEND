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
from .serializers import (
    MessageSerializer, ConversationSerializer,
    SharedCommunitySerializer, SharedCircleSerializer,
)

User = get_user_model()


class MessageHistoryView(generics.ListAPIView):
    """
    GET /api/chat/<community_id>/history/  -> last messages, for loading
    chat screen before the WebSocket connection takes over live updates.
    """
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    # This view's own `[:50]` slice below IS the pagination — the
    # project-wide PageNumberPagination (PAGE_SIZE=20) would otherwise
    # wrap on top of it and silently truncate 50 messages down to 20,
    # with no `next` link the frontend ever follows to get the rest.
    pagination_class = None

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
    pagination_class = None  # see MessageHistoryView.pagination_class

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
    pagination_class = None  # see MessageHistoryView.pagination_class

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


# ---------------------------------------------------------------------
# Sharing a Post / CircleQuestion / Community / Circle into a chat message
# ---------------------------------------------------------------------
# WhatsApp-style "forward" — but for in-app content instead of a file. The
# share icon on a Post/Question/Community/Circle opens a picker of the
# person's DMs/communities/circles (frontend ShareSheet), and picking one
# posts here rather than through the WebSocket — simplest for the sharing
# UI to fire a single request from wherever it was opened (a feed, a Q&A
# board, a community page) without first needing a live socket to that
# specific room open in the same tab.

SHARE_TYPES = {
    'post': 'shared_post',
    'question': 'shared_question',
    'community': 'shared_community',
    'circle': 'shared_circle',
}


def _resolve_share_target(share_type, share_id):
    """Returns (field_name, instance) for a valid {type, id} share payload,
    or (None, None) if the type is unrecognised or the object doesn't
    exist — callers turn that into a 400."""
    field = SHARE_TYPES.get(share_type)
    if not field or not share_id:
        return None, None
    try:
        if share_type == 'post':
            from posts.models import Post
            return field, Post.objects.get(pk=share_id)
        if share_type == 'question':
            from circles.models import CircleQuestion
            return field, CircleQuestion.objects.get(pk=share_id)
        if share_type == 'community':
            from communities.models import Community
            return field, Community.objects.get(pk=share_id)
        if share_type == 'circle':
            from circles.models import Circle
            return field, Circle.objects.get(pk=share_id)
    except Exception:
        return None, None
    return None, None


def _broadcast_share(room_group_name, message, data, extra=None):
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    channel_layer = get_channel_layer()
    payload = {
        'type': 'chat_message',
        'id': str(message.id),
        'body': message.body,
        'shared_post': data['shared_post'],
        'shared_question': data['shared_question'],
        'shared_community': data['shared_community'],
        'shared_circle': data['shared_circle'],
        'sender': message.sender.username,
        'sender_id': str(message.sender_id),
        'created_at': message.created_at.isoformat(),
    }
    if extra:
        payload.update(extra)
    async_to_sync(channel_layer.group_send)(room_group_name, payload)


class DMShareView(APIView):
    """
    POST /api/chat/dm/<user_id>/share/  body: {"share_type": "post"|"question"|"community"|"circle",
    "share_id": "<uuid>", "body": "optional caption"}

    Shares a post/question/community/circle into a DM instead of typing a
    plain-text message.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        target = get_object_or_404(User, pk=user_id)
        if target.id == request.user.id:
            return Response({'detail': "You can't message yourself."}, status=status.HTTP_400_BAD_REQUEST)
        if _blocked_either_way(request.user, target):
            return Response({'detail': "You can't message this user."}, status=status.HTTP_400_BAD_REQUEST)

        field, obj = _resolve_share_target(request.data.get('share_type'), request.data.get('share_id'))
        if not field:
            return Response({'detail': 'Nothing to share — that post, question, community or circle no longer exists.'},
                             status=status.HTTP_400_BAD_REQUEST)

        message = Message.objects.create(
            recipient=target,
            sender=request.user,
            body=(request.data.get('body') or '').strip(),
            **{field: obj},
        )
        data = MessageSerializer(message, context={'request': request}).data

        pair = sorted([str(request.user.id), str(target.id)])
        _broadcast_share(
            f'dm_{pair[0]}_{pair[1]}', message, data,
            extra={'recipient_id': str(target.id), 'read_at': None},
        )
        return Response(data, status=status.HTTP_201_CREATED)


class CommunityChatShareView(APIView):
    """POST /api/chat/<community_id>/share/ — same as DMShareView but into
    a community's live chat room. Membership-gated like every other
    community chat action (MessageHistoryView, ChatConsumer.connect)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, community_id):
        if not Membership.objects.filter(user=request.user, community_id=community_id).exists():
            raise PermissionDenied('Join this community to chat here.')

        field, obj = _resolve_share_target(request.data.get('share_type'), request.data.get('share_id'))
        if not field:
            return Response({'detail': 'Nothing to share — that post, question, community or circle no longer exists.'},
                             status=status.HTTP_400_BAD_REQUEST)

        message = Message.objects.create(
            community_id=community_id,
            sender=request.user,
            body=(request.data.get('body') or '').strip(),
            **{field: obj},
        )
        data = MessageSerializer(message, context={'request': request}).data
        _broadcast_share(f'chat_{community_id}', message, data)
        return Response(data, status=status.HTTP_201_CREATED)


class CircleChatShareView(APIView):
    """POST /api/chat/circle/<circle_id>/share/ — same as
    CommunityChatShareView but into a circle's live chat room."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, circle_id):
        from circles.models import CircleMembership
        if not CircleMembership.objects.filter(user=request.user, circle_id=circle_id).exists():
            raise PermissionDenied('Join this circle to chat here.')

        field, obj = _resolve_share_target(request.data.get('share_type'), request.data.get('share_id'))
        if not field:
            return Response({'detail': 'Nothing to share — that post, question, community or circle no longer exists.'},
                             status=status.HTTP_400_BAD_REQUEST)

        message = Message.objects.create(
            circle_id=circle_id,
            sender=request.user,
            body=(request.data.get('body') or '').strip(),
            **{field: obj},
        )
        data = MessageSerializer(message, context={'request': request}).data
        _broadcast_share(f'circle_chat_{circle_id}', message, data)
        return Response(data, status=status.HTTP_201_CREATED)


class ShareTargetsView(APIView):
    """
    GET /api/chat/share-targets/ -> {"dms": [...], "communities": [...], "circles": [...]}

    Powers the ShareSheet picker (frontend): everywhere the signed-in user
    could plausibly forward a post/question/community/circle to — their
    existing DM conversations, plus every community/circle they belong to.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.db.models import Count
        from communities.models import Community
        from circles.models import Circle
        from users.serializers import UserSerializer

        me = request.user
        messages = (
            Message.objects.filter(Q(sender=me) | Q(recipient=me))
            .exclude(recipient__isnull=True)
            .select_related('sender', 'recipient')
            .order_by('-created_at')
        )
        seen = set()
        dms = []
        for m in messages:
            other = m.recipient if m.sender_id == me.id else m.sender
            if other.id in seen:
                continue
            seen.add(other.id)
            dms.append(UserSerializer(other).data)

        communities = Community.objects.filter(members=me)
        circles = Circle.objects.filter(members=me)

        return Response({
            'dms': dms,
            'communities': SharedCommunitySerializer(communities, many=True, context={'request': request}).data,
            'circles': SharedCircleSerializer(circles, many=True, context={'request': request}).data,
        })
