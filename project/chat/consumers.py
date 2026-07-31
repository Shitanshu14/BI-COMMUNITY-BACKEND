import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket endpoint: ws://<host>/ws/chat/<community_id>/
    One Channels "group" per community = one live chat room, matching the
    'Chat' tab in the Feed | Chat | Members | Activities | Resources layout.
    """

    async def connect(self):
        self.community_id = self.scope['url_route']['kwargs']['community_id']
        self.room_group_name = f'chat_{self.community_id}'

        if not self.scope['user'].is_authenticated:
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        body = data.get('message', '').strip()
        if not body:
            return

        message = await self.save_message(body)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'id': str(message.id),
                'body': message.body,
                'sender': self.scope['user'].username,
                'sender_id': str(self.scope['user'].id),
                'created_at': message.created_at.isoformat(),
            },
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def save_message(self, body):
        from .models import Message
        return Message.objects.create(
            community_id=self.community_id,
            sender=self.scope['user'],
            body=body,
        )
