from django.urls import path

from .views import (
    SupportStatsView, SupportUserListView, SupportUserDetailView, SupportUserToggleActiveView,
    SupportCommunityListView, SupportCommunityDetailView, SupportCommunityMembersView,
    SupportCommunityMemberRemoveView, SupportCommunityToggleHoldView,
    SupportCircleListView, SupportCircleDetailView, SupportCircleMembersView, SupportCircleMemberRemoveView,
    SupportPostDeleteView,
    SupportTicketCreateView, SupportTicketListView, SupportTicketResolveView,
)

urlpatterns = [
    path('stats/', SupportStatsView.as_view(), name='support-stats'),

    path('users/', SupportUserListView.as_view(), name='support-users'),
    path('users/<uuid:pk>/', SupportUserDetailView.as_view(), name='support-user-detail'),
    path('users/<uuid:pk>/toggle-active/', SupportUserToggleActiveView.as_view(), name='support-user-toggle-active'),

    path('communities/', SupportCommunityListView.as_view(), name='support-communities'),
    path('communities/<uuid:pk>/', SupportCommunityDetailView.as_view(), name='support-community-detail'),
    path('communities/<uuid:pk>/toggle-hold/', SupportCommunityToggleHoldView.as_view(), name='support-community-toggle-hold'),
    path('communities/<uuid:pk>/members/', SupportCommunityMembersView.as_view(), name='support-community-members'),
    path('communities/<uuid:pk>/members/<uuid:user_id>/', SupportCommunityMemberRemoveView.as_view(), name='support-community-member-remove'),

    path('circles/', SupportCircleListView.as_view(), name='support-circles'),
    path('circles/<uuid:pk>/', SupportCircleDetailView.as_view(), name='support-circle-detail'),
    path('circles/<uuid:pk>/members/', SupportCircleMembersView.as_view(), name='support-circle-members'),
    path('circles/<uuid:pk>/members/<uuid:user_id>/', SupportCircleMemberRemoveView.as_view(), name='support-circle-member-remove'),

    path('posts/<uuid:pk>/', SupportPostDeleteView.as_view(), name='support-post-delete'),

    # Ticket create is public (see SupportTicketCreateView) — deliberately
    # under a distinct path (not just POST on the same 'tickets/' list
    # route) so the AllowAny surface is obvious at a glance in this file.
    path('tickets/create/', SupportTicketCreateView.as_view(), name='support-ticket-create'),
    path('tickets/', SupportTicketListView.as_view(), name='support-tickets'),
    path('tickets/<uuid:pk>/resolve/', SupportTicketResolveView.as_view(), name='support-ticket-resolve'),
]
