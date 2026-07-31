from django.urls import path

from .views import MessageHistoryView

urlpatterns = [
    path('<uuid:community_id>/history/', MessageHistoryView.as_view(), name='chat-history'),
]
