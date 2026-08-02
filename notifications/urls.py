from django.urls import path

from .views import NotificationListView, unread_count, mark_read, mark_all_read

urlpatterns = [
    path('', NotificationListView.as_view(), name='notification-list'),
    path('unread-count/', unread_count, name='notification-unread-count'),
    path('<uuid:pk>/read/', mark_read, name='notification-mark-read'),
    path('mark-all-read/', mark_all_read, name='notification-mark-all-read'),
]
