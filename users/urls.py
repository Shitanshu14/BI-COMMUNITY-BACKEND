from django.urls import path

from .views import (
    RegisterView, MeView, UserDetailView,
    CookieTokenObtainPairView, CookieTokenRefreshView, LogoutView,
    ResendVerificationEmailView, ConfirmEmailView,
    PasswordResetRequestView, PasswordResetConfirmView,
)
from follows.views import FollowUserView, UnfollowUserView, FollowersListView, FollowingListView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CookieTokenObtainPairView.as_view(), name='login'),           # POST email+password -> httpOnly cookies
    path('login/refresh/', CookieTokenRefreshView.as_view(), name='login-refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),

    path('email/resend/', ResendVerificationEmailView.as_view(), name='email-resend'),
    path('email/confirm/', ConfirmEmailView.as_view(), name='email-confirm'),

    path('password/reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password/reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),

    path('<uuid:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('<uuid:pk>/follow/', FollowUserView.as_view(), name='user-follow'),
    path('<uuid:pk>/unfollow/', UnfollowUserView.as_view(), name='user-unfollow'),
    path('<uuid:pk>/followers/', FollowersListView.as_view(), name='user-followers'),
    path('<uuid:pk>/following/', FollowingListView.as_view(), name='user-following'),
]
