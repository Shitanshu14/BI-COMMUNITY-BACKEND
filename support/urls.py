from django.urls import path

from .views import (
    SupportStatsView, SupportUserListView, SupportUserToggleActiveView,
    SupportCommunityListView, SupportCommunityMembersView,
    SupportCircleListView, SupportCircleMembersView,
)

urlpatterns = [
    path('stats/', SupportStatsView.as_view(), name='support-stats'),
    path('users/', SupportUserListView.as_view(), name='support-users'),
    path('users/<uuid:pk>/toggle-active/', SupportUserToggleActiveView.as_view(), name='support-user-toggle-active'),
    path('communities/', SupportCommunityListView.as_view(), name='support-communities'),
    path('communities/<uuid:pk>/members/', SupportCommunityMembersView.as_view(), name='support-community-members'),
    path('circles/', SupportCircleListView.as_view(), name='support-circles'),
    path('circles/<uuid:pk>/members/', SupportCircleMembersView.as_view(), name='support-circle-members'),
]
