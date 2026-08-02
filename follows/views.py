from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import Notification
from notifications.tasks import create_notification
from users.serializers import UserSerializer
from .models import Follow
from .serializers import FollowRequestSerializer

User = get_user_model()


class FollowUserView(APIView):
    """
    POST /api/users/<id>/follow/
    Public account -> follows immediately (status=accepted).
    Private account -> creates a pending request; the target has to accept
    it from their requests inbox before it counts as a real follow.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        if target.id == request.user.id:
            return Response({'detail': "You can't follow yourself."}, status=status.HTTP_400_BAD_REQUEST)

        follow, created = Follow.objects.get_or_create(
            follower=request.user,
            following=target,
            defaults={'status': Follow.Status.PENDING if target.is_private else Follow.Status.ACCEPTED},
        )

        if created:
            if follow.status == Follow.Status.ACCEPTED:
                create_notification.delay(
                    recipient_id=str(target.id), verb=Notification.Verb.NEW_FOLLOWER,
                    actor_id=str(request.user.id), target_id=str(request.user.id),
                )
            else:
                create_notification.delay(
                    recipient_id=str(target.id), verb=Notification.Verb.FOLLOW_REQUESTED,
                    actor_id=str(request.user.id), target_id=str(follow.id),
                )

        return Response({'status': follow.status}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class UnfollowUserView(APIView):
    """POST /api/users/<id>/unfollow/ — also cancels a still-pending request."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        deleted, _ = Follow.objects.filter(follower=request.user, following_id=pk).delete()
        return Response({'status': 'unfollowed' if deleted else 'not following'})


class FollowersListView(generics.ListAPIView):
    """GET /api/users/<id>/followers/ — accepted followers only."""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return User.objects.filter(
            following_set__following_id=self.kwargs['pk'],
            following_set__status=Follow.Status.ACCEPTED,
        )


class FollowingListView(generics.ListAPIView):
    """GET /api/users/<id>/following/ — accepted follows only."""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return User.objects.filter(
            follower_set__follower_id=self.kwargs['pk'],
            follower_set__status=Follow.Status.ACCEPTED,
        )


class MyFollowRequestsView(generics.ListAPIView):
    """GET /api/follow-requests/ — pending requests waiting on *me* to approve."""
    serializer_class = FollowRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Follow.objects.filter(following=self.request.user, status=Follow.Status.PENDING).select_related('follower')


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def accept_follow_request(request, pk):
    """POST /api/follow-requests/<follow_id>/accept/"""
    follow = get_object_or_404(Follow, pk=pk, following=request.user, status=Follow.Status.PENDING)
    follow.status = Follow.Status.ACCEPTED
    follow.save(update_fields=['status'])
    create_notification.delay(
        recipient_id=str(follow.follower_id), verb=Notification.Verb.FOLLOW_ACCEPTED,
        actor_id=str(request.user.id), target_id=str(request.user.id),
    )
    return Response({'status': 'accepted'})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def reject_follow_request(request, pk):
    """POST /api/follow-requests/<follow_id>/reject/"""
    follow = get_object_or_404(Follow, pk=pk, following=request.user, status=Follow.Status.PENDING)
    follow.delete()
    return Response({'status': 'rejected'})
