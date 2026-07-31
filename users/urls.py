from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import RegisterView, MeView, UserDetailView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', TokenObtainPairView.as_view(), name='login'),          # POST email+password -> tokens
    path('login/refresh/', TokenRefreshView.as_view(), name='login-refresh'),
    path('me/', MeView.as_view(), name='me'),
    path('<uuid:pk>/', UserDetailView.as_view(), name='user-detail'),
]
