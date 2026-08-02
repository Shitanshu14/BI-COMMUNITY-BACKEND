"""
Channels middleware that authenticates WebSocket connections using the same
JWT the REST API uses (rest_framework_simplejwt), instead of Django session
cookies.

Two token sources are supported:
1. The httpOnly `access_token` cookie — this is what the browser web
   dashboard sends automatically on the WS handshake (same as any other
   request to the API's domain), now that tokens live in cookies instead
   of localStorage.
2. `?token=<access_token>` query string — used by the Flutter app, which
   has no browser cookie jar and instead holds the token itself
   (see users/views.py `wants_tokens_in_body`).
"""

from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def get_user_from_token(token):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        validated_token = AccessToken(token)
        user = User.objects.get(id=validated_token['user_id'])
        return user
    except (InvalidToken, TokenError, User.DoesNotExist, KeyError):
        return AnonymousUser()


def _extract_token(scope):
    # 1. Query string (Flutter app)
    query_string = scope.get('query_string', b'').decode()
    params = parse_qs(query_string)
    token = params.get('token', [None])[0]
    if token:
        return token

    # 2. httpOnly cookie (browser web dashboard)
    headers = dict(scope.get('headers') or [])
    raw_cookie = headers.get(b'cookie', b'').decode()
    if raw_cookie:
        cookie = SimpleCookie()
        cookie.load(raw_cookie)
        morsel = cookie.get(settings.AUTH_COOKIE_ACCESS)
        if morsel:
            return morsel.value

    return None


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        token = _extract_token(scope)

        if token:
            scope['user'] = await get_user_from_token(token)
        else:
            scope['user'] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
