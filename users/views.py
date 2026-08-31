from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Block
from .serializers import (
    RegisterSerializer, UserSerializer, UserProfileSerializer, BlockAwareTokenObtainPairSerializer,
    PasswordResetRequestSerializer, PasswordResetConfirmSerializer,
)
from .tasks import send_verification_email, send_password_reset_email, email_verification_token

User = get_user_model()


# ----------------------------------------------------------------------
# Cookie helpers — access/refresh tokens are set as httpOnly cookies, never
# returned in the JSON body, so JS on the page (and therefore any XSS
# payload) can never read them. The Flutter app instead reads the tokens
# from the response body (see `include_tokens_in_body`) and sends them
# back as a normal Authorization header, since it has no browser cookie jar.
# ----------------------------------------------------------------------

def set_auth_cookies(response, access, refresh=None):
    cookie_kwargs = dict(
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path='/',
    )
    response.set_cookie(settings.AUTH_COOKIE_ACCESS, access, max_age=int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()), **cookie_kwargs)
    if refresh:
        response.set_cookie(settings.AUTH_COOKIE_REFRESH, refresh, max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()), **cookie_kwargs)
    return response


def clear_auth_cookies(response):
    response.delete_cookie(settings.AUTH_COOKIE_ACCESS, path='/', domain=settings.AUTH_COOKIE_DOMAIN)
    response.delete_cookie(settings.AUTH_COOKIE_REFRESH, path='/', domain=settings.AUTH_COOKIE_DOMAIN)
    return response


def wants_tokens_in_body(request):
    """
    The Flutter app (or any non-browser client) can't use httpOnly cookies
    the way a browser does, so it sends this header to opt into getting the
    tokens back in the JSON body instead, and is then responsible for
    storing them securely (e.g. flutter_secure_storage) and sending them
    back via `Authorization: Bearer <token>`.
    """
    return request.headers.get('X-Client-Type', '').lower() == 'mobile'


class RegisterView(generics.CreateAPIView):
    """POST /api/users/register/ — Signup (Phase-1 MVP feature #1)."""
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'register'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        send_verification_email.delay(str(user.id))

        refresh = RefreshToken.for_user(user)
        body = {'user': UserSerializer(user).data}
        if wants_tokens_in_body(request):
            body['access'] = str(refresh.access_token)
            body['refresh'] = str(refresh)

        response = Response(body, status=status.HTTP_201_CREATED)
        if not wants_tokens_in_body(request):
            set_auth_cookies(response, str(refresh.access_token), str(refresh))
        return response


class CookieTokenObtainPairView(TokenObtainPairView):
    """POST /api/users/login/ — email+password -> httpOnly cookies (or JSON for mobile)."""
    serializer_class = BlockAwareTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access = serializer.validated_data['access']
        refresh = serializer.validated_data['refresh']

        user = serializer.user
        body = {'user': UserSerializer(user).data}
        if wants_tokens_in_body(request):
            body['access'] = str(access)
            body['refresh'] = str(refresh)

        response = Response(body, status=status.HTTP_200_OK)
        if not wants_tokens_in_body(request):
            response = set_auth_cookies(response, str(access), str(refresh))
        return response


class CookieTokenRefreshView(APIView):
    """POST /api/users/login/refresh/ — reads refresh token from cookie (or body for mobile)."""
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        raw_refresh = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH) or request.data.get('refresh')
        if not raw_refresh:
            return Response({'detail': 'No refresh token provided.'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            refresh = RefreshToken(raw_refresh)
            access = refresh.access_token
        except TokenError:
            return Response({'detail': 'Refresh token invalid or expired.'}, status=status.HTTP_401_UNAUTHORIZED)

        body = {}
        if wants_tokens_in_body(request):
            body['access'] = str(access)
            response = Response(body, status=status.HTTP_200_OK)
        else:
            response = Response(body, status=status.HTTP_200_OK)
            set_auth_cookies(response, str(access))
        return response


class LogoutView(APIView):
    """POST /api/users/logout/ — blacklists the refresh token and clears cookies."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        raw_refresh = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH) or request.data.get('refresh')
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                pass

        response = Response({'status': 'logged out'})
        return clear_auth_cookies(response)


class MeView(APIView):
    """GET/PATCH /api/users/me/ — current user's profile."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        data = UserProfileSerializer(request.user, context={'request': request}).data
        # Self-only fields — deliberately not on UserProfileSerializer
        # itself (that's also used for *other* people's profiles via
        # UserDetailView below, and who's on the support team isn't
        # public information). The frontend uses these to decide whether
        # to show the "Support Dashboard" sidebar link at all.
        data['is_support'] = request.user.is_support
        data['is_staff'] = request.user.is_staff
        return Response(data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class UserDetailView(generics.RetrieveAPIView):
    """GET /api/users/<id>/ — profile view (posts/communities/follow counts).
    Requires login, same as posts/communities (no anonymous browsing)."""
    queryset = User.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]


# ----------------------------------------------------------------------
# Block / unblock
# ----------------------------------------------------------------------

class BlockUserView(APIView):
    """
    POST /api/users/<id>/block/ — blocks the target user. This immediately
    removes any existing follow relationship in either direction, and from
    then on neither person sees the other's posts/comments/search results
    (enforced everywhere Block is checked — see posts/views.py, search).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        if target.id == request.user.id:
            return Response({'detail': "You can't block yourself."}, status=status.HTTP_400_BAD_REQUEST)

        Block.objects.get_or_create(blocker=request.user, blocked=target)

        from follows.models import Follow
        Follow.objects.filter(follower=request.user, following=target).delete()
        Follow.objects.filter(follower=target, following=request.user).delete()

        return Response({'status': 'blocked'})


class UnblockUserView(APIView):
    """POST /api/users/<id>/unblock/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        deleted, _ = Block.objects.filter(blocker=request.user, blocked_id=pk).delete()
        return Response({'status': 'unblocked' if deleted else 'not blocked'})


class BlockedUsersListView(generics.ListAPIView):
    """GET /api/users/blocked/ — accounts *I* have blocked (for a Settings page)."""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(blocked_by_set__blocker=self.request.user).order_by('username')


# ----------------------------------------------------------------------
# Account deactivation
# ----------------------------------------------------------------------

class DeactivateAccountView(APIView):
    """
    POST /api/users/deactivate/  body: {password}

    Soft-deletes the account: sets is_active=False (Django's built-in flag,
    already used by the Admin's "Deactivate selected users" action). Once
    set, every feed/search query that filters on author__is_active=True
    stops showing this user's posts, and Simple JWT refuses to authenticate
    them, so they're logged out on their next request. Their data isn't
    deleted — a superuser can flip is_active back on from Django Admin.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        if not username or not password:
            return Response({'detail': 'Username and password are required.'}, status=status.HTTP_400_BAD_REQUEST)
            
        user = request.user
        if username.lower() not in [user.username.lower(), user.email.lower()]:
            return Response({'detail': 'Incorrect username.'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(password):
            return Response({'detail': 'Incorrect password.'}, status=status.HTTP_400_BAD_REQUEST)

        request.user.is_active = False
        request.user.save(update_fields=['is_active'])

        raw_refresh = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH) or request.data.get('refresh')
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                pass

        response = Response({'status': 'deactivated'})
        return clear_auth_cookies(response)


# ----------------------------------------------------------------------
# Email verification (signup confirmation)
# ----------------------------------------------------------------------

class ResendVerificationEmailView(APIView):
    """POST /api/users/email/resend/ — re-sends the confirmation link."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'email_verify'

    def post(self, request):
        if request.user.email_confirmed:
            return Response({'detail': 'Email already confirmed.'}, status=status.HTTP_400_BAD_REQUEST)
        send_verification_email.delay(str(request.user.id))
        return Response({'status': 'sent'})


class ConfirmEmailView(APIView):
    """POST /api/users/email/confirm/  body: {uid, token}"""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'email_verify'

    def post(self, request):
        uid = request.data.get('uid')
        token = request.data.get('token')
        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return Response({'detail': 'Invalid link.'}, status=status.HTTP_400_BAD_REQUEST)

        if not email_verification_token.check_token(user, token):
            return Response({'detail': 'Link is invalid or has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        user.email_confirmed = True
        user.save(update_fields=['email_confirmed'])
        return Response({'status': 'confirmed'})


# ----------------------------------------------------------------------
# Password reset
# ----------------------------------------------------------------------

class PasswordResetRequestView(APIView):
    """POST /api/users/password/reset/  body: {email}"""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        user = User.objects.filter(email__iexact=email).first()
        if user:
            send_password_reset_email.delay(str(user.id))

        # Always the same response, whether or not the email exists —
        # otherwise this endpoint becomes a way to check who has an account.
        return Response({'status': 'If that email exists, a reset link has been sent.'})


class PasswordResetConfirmView(APIView):
    """POST /api/users/password/reset/confirm/  body: {uid, token, new_password}"""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uid = serializer.validated_data['uid']
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return Response({'detail': 'Invalid link.'}, status=status.HTTP_400_BAD_REQUEST)

        if not default_token_generator.check_token(user, token):
            return Response({'detail': 'Link is invalid or has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=['password'])

        # Save the new password to PasswordHistory
        from users.models import PasswordHistory
        PasswordHistory.objects.create(user=user, password_hash=user.password)

        return Response({'status': 'Password updated. You can log in now.'})
