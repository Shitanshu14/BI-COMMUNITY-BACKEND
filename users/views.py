from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import (
    RegisterSerializer, UserSerializer, UserProfileSerializer,
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
        return Response(UserProfileSerializer(request.user, context={'request': request}).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class UserDetailView(generics.RetrieveAPIView):
    """GET /api/users/<id>/ — public profile view (posts/communities/follow counts)."""
    queryset = User.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


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
        return Response({'status': 'Password updated. You can log in now.'})
