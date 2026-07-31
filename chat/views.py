from rest_framework import generics, permissions

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
        return Message.objects.filter(community_id=community_id).select_related('sender').order_by('-created_at')[:50]
