from django.urls import path

from .views import MyFollowRequestsView, accept_follow_request, reject_follow_request

urlpatterns = [
    path('', MyFollowRequestsView.as_view(), name='follow-requests'),
    path('<uuid:pk>/accept/', accept_follow_request, name='follow-request-accept'),
    path('<uuid:pk>/reject/', reject_follow_request, name='follow-request-reject'),
]
