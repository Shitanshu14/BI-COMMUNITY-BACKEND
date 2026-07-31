from rest_framework import generics, permissions

from .models import VerificationRequest
from .serializers import VerificationRequestSerializer


class VerificationRequestCreateView(generics.CreateAPIView):
    """POST /api/verification/request/ — user submits proof, status starts PENDING."""
    serializer_class = VerificationRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MyVerificationStatusView(generics.ListAPIView):
    """GET /api/verification/me/ — see own request history/status."""
    serializer_class = VerificationRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return VerificationRequest.objects.filter(user=self.request.user)
