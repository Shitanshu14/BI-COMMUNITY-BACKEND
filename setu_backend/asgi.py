"""
ASGI config for setu_backend project.
Routes plain HTTP to Django views, and ws:// traffic to Channels consumers
(this is what makes real-time chat + notifications work — see chat/routing.py).
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'setu_backend.settings')

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from setu_backend.jwt_auth_middleware import JWTAuthMiddlewareStack
import chat.routing
import notifications.routing

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': JWTAuthMiddlewareStack(
        URLRouter(
            chat.routing.websocket_urlpatterns + notifications.routing.websocket_urlpatterns
        )
    ),
})
