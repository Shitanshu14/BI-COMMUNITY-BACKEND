from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CircleViewSet, MyCircleInvitesView, AcceptCircleInviteView, DeclineCircleInviteView,
    CircleQuestionListCreateView, CircleQuestionDetailView, CircleAnswerCreateView, CircleAnswerAcceptView,
)

router = DefaultRouter()
router.register('', CircleViewSet, basename='circle')

urlpatterns = [
    # NOTE: these must come before router.urls — the router's default pk
    # regex ([^/.]+) would otherwise swallow "invites"/"<id>/questions" as
    # if they were circle sub-resources routed into CircleViewSet.
    path('invites/', MyCircleInvitesView.as_view(), name='circle-invites'),
    path('invites/<uuid:pk>/accept/', AcceptCircleInviteView.as_view(), name='circle-invite-accept'),
    path('invites/<uuid:pk>/decline/', DeclineCircleInviteView.as_view(), name='circle-invite-decline'),

    # Q&A board for a circle (see circles/models.py CircleQuestion docstring)
    path('<uuid:circle_id>/questions/', CircleQuestionListCreateView.as_view(), name='circle-question-list'),
    path('<uuid:circle_id>/questions/<uuid:pk>/', CircleQuestionDetailView.as_view(), name='circle-question-detail'),
    path('<uuid:circle_id>/questions/<uuid:pk>/answers/', CircleAnswerCreateView.as_view(), name='circle-answer-create'),
    path(
        '<uuid:circle_id>/questions/<uuid:qid>/answers/<uuid:aid>/accept/',
        CircleAnswerAcceptView.as_view(), name='circle-answer-accept',
    ),
] + router.urls
