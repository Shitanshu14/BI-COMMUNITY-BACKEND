from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/dm/(?P<user_id>[0-9a-f-]+)/$', consumers.DMConsumer.as_asgi()),
    re_path(r'ws/chat/circle/(?P<circle_id>[0-9a-f-]+)/$', consumers.CircleChatConsumer.as_asgi()),
    re_path(r'ws/chat/(?P<community_id>[0-9a-f-]+)/$', consumers.ChatConsumer.as_asgi()),
]
