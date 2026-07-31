"""
Channels middleware that authenticates WebSocket connections using the same
JWT access token the REST API uses (rest_framework_simplejwt), instead of
Django session cookies.

The default `channels.auth.AuthMiddlewareStack` only understands session
cookies, which a Flutter app talking to a JWT-based API will never send —
so every websocket connection was landing as AnonymousUser and getting
closed. This middleware reads the token from the `?token=<access_token>`
query string param instead.

Flutter side just needs to connect to:
    ws://<host>/ws/chat/<community_id>/?token=<access_token>
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
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


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        params = parse_qs(query_string)
        token = params.get('token', [None])[0]

        if token:
            scope['user'] = await get_user_from_token(token)
        else:
            scope['user'] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
