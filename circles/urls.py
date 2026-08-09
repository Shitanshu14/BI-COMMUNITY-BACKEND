from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CircleViewSet, MyCircleInvitesView, AcceptCircleInviteView, DeclineCircleInviteView,
)

router = DefaultRouter()
router.register('', CircleViewSet, basename='circle')

urlpatterns = [
    # NOTE: these must come before router.urls — the router's default pk
    # regex ([^/.]+) would otherwise swallow "invites" as if it were a
    # circle id and route it into CircleViewSet.retrieve() instead.
    path('invites/', MyCircleInvitesView.as_view(), name='circle-invites'),
    path('invites/<uuid:pk>/accept/', AcceptCircleInviteView.as_view(), name='circle-invite-accept'),
    path('invites/<uuid:pk>/decline/', DeclineCircleInviteView.as_view(), name='circle-invite-decline'),
] + router.urls
