from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError

from .models import VerificationRequest
from .serializers import VerificationRequestSerializer


class VerificationRequestCreateView(generics.CreateAPIView):
    """POST /api/verification/request/ — user submits proof, status starts PENDING."""
    serializer_class = VerificationRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        # Without this, a user could submit repeatedly and flood the admin
        # review queue with duplicates of the same pending request.
        already_pending = VerificationRequest.objects.filter(
            user=self.request.user, status=VerificationRequest.Status.PENDING
        ).exists()
        if already_pending:
            raise ValidationError('You already have a pending verification request.')
        serializer.save(user=self.request.user)


class MyVerificationStatusView(generics.ListAPIView):
    """GET /api/verification/me/ — see own request history/status."""
    serializer_class = VerificationRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return VerificationRequest.objects.filter(user=self.request.user)
