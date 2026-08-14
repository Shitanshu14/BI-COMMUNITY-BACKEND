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
from .models import (
    Circle, CircleMembership, CircleInvite, CircleQuestion, CircleAnswer,
    CircleEvent, CircleEventRSVP,
)
from .serializers import (
    CircleSerializer, CircleInviteSerializer,
    CircleQuestionSerializer, CircleQuestionDetailSerializer, CircleAnswerSerializer,
    CircleEventSerializer,
)

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
                ),
                is_owner_val=Exists(
                    CircleMembership.objects.filter(
                        user=user, circle=OuterRef('pk'), role=CircleMembership.Role.OWNER
                    )
                ),
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


def _member_circle_or_403(user, circle_id):
    """Shared guard for every Q&A endpoint below: 404 if the circle
    doesn't exist, 403 if the requester isn't a member of it (Circles are
    private — see Circle model docstring)."""
    circle = get_object_or_404(Circle, pk=circle_id)
    if not CircleMembership.objects.filter(user=user, circle=circle).exists():
        return circle, False
    return circle, True


class CircleQuestionListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/circles/<circle_id>/questions/  -> Q&A board for this circle
    POST /api/circles/<circle_id>/questions/  -> ask a new question
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return CircleQuestionSerializer

    def _circle(self):
        circle, is_member = _member_circle_or_403(self.request.user, self.kwargs['circle_id'])
        if not is_member:
            return None
        return circle

    def get_queryset(self):
        circle = self._circle()
        if circle is None:
            return CircleQuestion.objects.none()
        return CircleQuestion.objects.filter(circle=circle).select_related('author').annotate(
            answer_count_val=Count('answers', distinct=True)
        )

    def list(self, request, *args, **kwargs):
        circle, is_member = _member_circle_or_403(request.user, kwargs['circle_id'])
        if not is_member:
            return Response({'detail': 'You must be a member of this circle.'}, status=status.HTTP_403_FORBIDDEN)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        circle, is_member = _member_circle_or_403(request.user, kwargs['circle_id'])
        if not is_member:
            return Response({'detail': 'You must be a member of this circle.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.save(circle=circle, author=request.user)
        out = CircleQuestionSerializer(question, context={'request': request})
        return Response({**out.data, 'answer_count': 0}, status=status.HTTP_201_CREATED)


class CircleQuestionDetailView(generics.RetrieveAPIView):
    """GET /api/circles/<circle_id>/questions/<id>/ -> question + full answer thread."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CircleQuestionDetailSerializer

    def get_object(self):
        circle, is_member = _member_circle_or_403(self.request.user, self.kwargs['circle_id'])
        if not is_member:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You must be a member of this circle.')
        return get_object_or_404(
            CircleQuestion.objects.select_related('author').prefetch_related('answers__author'),
            pk=self.kwargs['pk'], circle=circle,
        )


class CircleAnswerCreateView(APIView):
    """POST /api/circles/<circle_id>/questions/<pk>/answers/ -> post an answer."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, circle_id, pk):
        circle, is_member = _member_circle_or_403(request.user, circle_id)
        if not is_member:
            return Response({'detail': 'You must be a member of this circle.'}, status=status.HTTP_403_FORBIDDEN)
        question = get_object_or_404(CircleQuestion, pk=pk, circle=circle)
        body = (request.data.get('body') or '').strip()
        if not body:
            return Response({'detail': 'body is required.'}, status=status.HTTP_400_BAD_REQUEST)
        answer = CircleAnswer.objects.create(question=question, author=request.user, body=body)

        if question.author_id != request.user.id:
            create_notification.delay(
                recipient_id=str(question.author_id),
                verb=Notification.Verb.CIRCLE_QUESTION_ANSWERED,
                actor_id=str(request.user.id),
                target_id=str(question.id),
            )
        return Response(CircleAnswerSerializer(answer).data, status=status.HTTP_201_CREATED)


class CircleAnswerAcceptView(APIView):
    """
    POST /api/circles/<circle_id>/questions/<qid>/answers/<aid>/accept/
    Only the question's own author, or the circle owner, can mark an
    answer accepted (mirrors how Stack Overflow scopes "accept").
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, circle_id, qid, aid):
        circle, is_member = _member_circle_or_403(request.user, circle_id)
        if not is_member:
            return Response({'detail': 'You must be a member of this circle.'}, status=status.HTTP_403_FORBIDDEN)
        question = get_object_or_404(CircleQuestion, pk=qid, circle=circle)
        answer = get_object_or_404(CircleAnswer, pk=aid, question=question)

        is_owner = CircleMembership.objects.filter(
            user=request.user, circle=circle, role=CircleMembership.Role.OWNER
        ).exists()
        if question.author_id != request.user.id and not is_owner:
            return Response(
                {'detail': "Only the question's author or the circle owner can accept an answer."},
                status=status.HTTP_403_FORBIDDEN,
            )

        CircleAnswer.objects.filter(question=question).update(is_accepted=False)
        answer.is_accepted = True
        answer.save(update_fields=['is_accepted'])
        question.is_solved = True
        question.save(update_fields=['is_solved'])

        if answer.author_id != request.user.id:
            create_notification.delay(
                recipient_id=str(answer.author_id),
                verb=Notification.Verb.CIRCLE_ANSWER_ACCEPTED,
                actor_id=str(request.user.id),
                target_id=str(question.id),
            )
        return Response(CircleAnswerSerializer(answer).data)


class CircleEventListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/circles/<circle_id>/events/  -> upcoming + past events, soonest first
    POST /api/circles/<circle_id>/events/  -> schedule a new event (any member)
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CircleEventSerializer

    def get_queryset(self):
        circle, is_member = _member_circle_or_403(self.request.user, self.kwargs['circle_id'])
        if not is_member:
            return CircleEvent.objects.none()
        return CircleEvent.objects.filter(circle=circle).select_related('created_by').prefetch_related('rsvp_set')

    def list(self, request, *args, **kwargs):
        circle, is_member = _member_circle_or_403(request.user, kwargs['circle_id'])
        if not is_member:
            return Response({'detail': 'You must be a member of this circle.'}, status=status.HTTP_403_FORBIDDEN)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        circle, is_member = _member_circle_or_403(request.user, kwargs['circle_id'])
        if not is_member:
            return Response({'detail': 'You must be a member of this circle.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save(circle=circle, created_by=request.user)
        # Creator is implicitly "going" — no need to RSVP to your own event.
        CircleEventRSVP.objects.create(event=event, user=request.user, status=CircleEventRSVP.Status.GOING)

        for member in circle.members.exclude(id=request.user.id):
            create_notification.delay(
                recipient_id=str(member.id),
                verb=Notification.Verb.CIRCLE_EVENT_CREATED,
                actor_id=str(request.user.id),
                target_id=str(event.id),
            )
        out = CircleEventSerializer(event, context={'request': request})
        return Response(out.data, status=status.HTTP_201_CREATED)


class CircleEventRSVPView(APIView):
    """POST /api/circles/<circle_id>/events/<pk>/rsvp/  {status: going|maybe|declined}"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, circle_id, pk):
        circle, is_member = _member_circle_or_403(request.user, circle_id)
        if not is_member:
            return Response({'detail': 'You must be a member of this circle.'}, status=status.HTTP_403_FORBIDDEN)
        event = get_object_or_404(CircleEvent, pk=pk, circle=circle)
        rsvp_status = request.data.get('status')
        if rsvp_status not in CircleEventRSVP.Status.values:
            return Response({'detail': 'status must be one of going/maybe/declined.'}, status=status.HTTP_400_BAD_REQUEST)
        CircleEventRSVP.objects.update_or_create(
            event=event, user=request.user, defaults={'status': rsvp_status}
        )
        return Response(CircleEventSerializer(event, context={'request': request}).data)


class CircleEventDeleteView(APIView):
    """DELETE /api/circles/<circle_id>/events/<pk>/ — creator or circle owner only."""
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, circle_id, pk):
        circle, is_member = _member_circle_or_403(request.user, circle_id)
        if not is_member:
            return Response({'detail': 'You must be a member of this circle.'}, status=status.HTTP_403_FORBIDDEN)
        event = get_object_or_404(CircleEvent, pk=pk, circle=circle)
        is_owner = CircleMembership.objects.filter(
            user=request.user, circle=circle, role=CircleMembership.Role.OWNER
        ).exists()
        if event.created_by_id != request.user.id and not is_owner:
            return Response({'detail': 'Only the event creator or circle owner can delete this.'}, status=status.HTTP_403_FORBIDDEN)
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
