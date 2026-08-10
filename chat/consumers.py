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

        # Previously any authenticated user could join ANY community's chat,
        # even ones they'd never joined — this brings chat in line with the
        # "join before you can post" rule already enforced on posts.
        if not await self.is_member():
            await self.close(code=4003)
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
    def is_member(self):
        from communities.models import Membership
        return Membership.objects.filter(
            user=self.scope['user'], community_id=self.community_id
        ).exists()

    @database_sync_to_async
    def save_message(self, body):
        from .models import Message
        return Message.objects.create(
            community_id=self.community_id,
            sender=self.scope['user'],
            body=body,
        )


class CircleChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket endpoint: ws://<host>/ws/chat/circle/<circle_id>/
    One Channels "group" per circle = one live chat room for that Circle's
    members. Mirrors ChatConsumer exactly, just scoped to Circle
    membership (circles/models.CircleMembership) instead of Community
    Membership — Circles are private/invite-only, so this is what actually
    powers the "For Chat" purpose on the Circle page.
    """

    async def connect(self):
        self.circle_id = self.scope['url_route']['kwargs']['circle_id']
        self.room_group_name = f'circle_chat_{self.circle_id}'

        if not self.scope['user'].is_authenticated:
            await self.close()
            return

        if not await self.is_member():
            await self.close(code=4003)
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
    def is_member(self):
        from circles.models import CircleMembership
        return CircleMembership.objects.filter(
            user=self.scope['user'], circle_id=self.circle_id
        ).exists()

    @database_sync_to_async
    def save_message(self, body):
        from .models import Message
        return Message.objects.create(
            circle_id=self.circle_id,
            sender=self.scope['user'],
            body=body,
        )


class DMConsumer(AsyncWebsocketConsumer):
    """
    WebSocket endpoint: ws://<host>/ws/dm/<other_user_id>/
    One Channels group per (me, other) pair, named with the two user ids
    sorted so both people's connections land in the same group regardless
    of who initiated it — group name is symmetric: dm_<id1>_<id2> where
    id1 < id2 alphabetically.
    """

    async def connect(self):
        self.my_id = str(self.scope['user'].id) if self.scope['user'].is_authenticated else None
        self.other_id = self.scope['url_route']['kwargs']['user_id']

        if not self.my_id:
            await self.close()
            return
        if self.my_id == self.other_id:
            await self.close(code=4004)
            return
        if await self.is_blocked():
            await self.close(code=4003)
            return

        pair = sorted([self.my_id, self.other_id])
        self.room_group_name = f'dm_{pair[0]}_{pair[1]}'
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        # Opening the thread reads whatever the other person already sent.
        # If anything actually changed, tell the group so their tab (if
        # open) can flip its ticks to "read" immediately.
        if await self.mark_read():
            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'read_receipt', 'reader_id': self.my_id},
            )

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
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
                'sender_id': self.my_id,
                'recipient_id': self.other_id,
                'read_at': None,
                'created_at': message.created_at.isoformat(),
            },
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    async def read_receipt(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def is_blocked(self):
        from users.models import Block
        return (
            Block.objects.filter(blocker_id=self.my_id, blocked_id=self.other_id).exists()
            or Block.objects.filter(blocker_id=self.other_id, blocked_id=self.my_id).exists()
        )

    @database_sync_to_async
    def mark_read(self):
        """Marks the other user's messages to me as read. Returns True if
        anything actually changed (so the caller only broadcasts a
        read_receipt when there's something new to report)."""
        from django.utils import timezone
        from .models import Message
        updated = Message.objects.filter(
            sender_id=self.other_id, recipient_id=self.my_id, read_at__isnull=True
        ).update(read_at=timezone.now())
        return updated > 0

    @database_sync_to_async
    def save_message(self, body):
        from .models import Message
        return Message.objects.create(
            recipient_id=self.other_id,
            sender=self.scope['user'],
            body=body,
        )
