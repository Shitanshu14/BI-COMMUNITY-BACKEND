"""
Cookie-based JWT authentication.

The web dashboard (browser) never sees the raw token — it's set as an
httpOnly cookie by the login/register/refresh views (see users/views.py),
so client-side JS (and therefore any XSS payload) cannot read or steal it.

The Flutter mobile app has no cookie jar in the same sense a browser does,
so it keeps sending `Authorization: Bearer <token>` like before — this
class supports both, cookie first, header as fallback.
"""

from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
        else:
            raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)

        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
