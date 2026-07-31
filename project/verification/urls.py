from django.urls import path

from .views import VerificationRequestCreateView, MyVerificationStatusView

urlpatterns = [
    path('request/', VerificationRequestCreateView.as_view(), name='verification-request'),
    path('me/', MyVerificationStatusView.as_view(), name='verification-me'),
]
