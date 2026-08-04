from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied

from communities.models import Membership
from .models import Message
from .serializers import MessageSerializer


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
