from django.urls import path

from .views import (
    MessageHistoryView, CircleMessageHistoryView, DMHistoryView, DMConversationsView, StartDMView,
    DMUnreadCountView, DMShareView, CommunityChatShareView, CircleChatShareView, ShareTargetsView,
)

urlpatterns = [
    path('dm/unread-count/', DMUnreadCountView.as_view(), name='dm-unread-count'),
    path('dm/', DMConversationsView.as_view(), name='dm-conversations'),
    path('share-targets/', ShareTargetsView.as_view(), name='chat-share-targets'),
    path('dm/<uuid:user_id>/start/', StartDMView.as_view(), name='dm-start'),
    path('dm/<uuid:user_id>/history/', DMHistoryView.as_view(), name='dm-history'),
    path('dm/<uuid:user_id>/share/', DMShareView.as_view(), name='dm-share'),
    path('circle/<uuid:circle_id>/history/', CircleMessageHistoryView.as_view(), name='circle-chat-history'),
    path('circle/<uuid:circle_id>/share/', CircleChatShareView.as_view(), name='circle-chat-share'),
    path('<uuid:community_id>/history/', MessageHistoryView.as_view(), name='chat-history'),
    path('<uuid:community_id>/share/', CommunityChatShareView.as_view(), name='chat-share'),
]
