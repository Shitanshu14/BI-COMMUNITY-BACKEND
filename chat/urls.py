from django.urls import path

from .views import (
    MessageHistoryView, DMHistoryView, DMConversationsView, StartDMView, DMUnreadCountView,
)

urlpatterns = [
    path('dm/unread-count/', DMUnreadCountView.as_view(), name='dm-unread-count'),
    path('dm/', DMConversationsView.as_view(), name='dm-conversations'),
    path('dm/<uuid:user_id>/start/', StartDMView.as_view(), name='dm-start'),
    path('dm/<uuid:user_id>/history/', DMHistoryView.as_view(), name='dm-history'),
    path('<uuid:community_id>/history/', MessageHistoryView.as_view(), name='chat-history'),
]
