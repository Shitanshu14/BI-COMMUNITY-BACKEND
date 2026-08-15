from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from channels.testing import WebsocketCommunicator
from asgiref.sync import async_to_sync
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework.test import APIClient, APITestCase

from setu_backend.asgi import application
from users.models import Block
from .models import Message

User = get_user_model()

# Channels needs a real broker (Redis in production) to pass messages
# between connections/processes. For a test we don't want to depend on a
# running Redis server, so we swap in Channels' in-memory layer — it's
# functionally identical for a single-process test, just not shared across
# processes, which is exactly what a test doesn't need.
IN_MEMORY_LAYER = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class DMFlowTest(TransactionTestCase):
    """
    End-to-end regression test for a reported bug: "messages I send don't
    show up in the conversation list." Root cause (confirmed by this test
    passing cleanly) was never in this code path — it was the WebSocket
    layer being unreachable in production because REDIS_HOST/REDIS_PORT
    weren't set on Render, so `send()` on the frontend silently no-opped
    (button disabled while status != "live") and no Message row was ever
    created. This test locks in that the actual send -> persist -> list
    pipeline is correct, so any future regression here gets caught in CI
    rather than discovered by a user screenshotting "no conversations yet."
    """

    def test_dm_message_persists_and_appears_in_conversation_list(self):
        alice = User.objects.create_user(username='alice_dm', email='alice_dm@example.com', password='TestPass123!')
        bob = User.objects.create_user(username='bob_dm', email='bob_dm@example.com', password='TestPass123!')
        alice_token = str(AccessToken.for_user(alice))
        bob_token = str(AccessToken.for_user(bob))

        async def run():
            comm_alice = WebsocketCommunicator(application, f'/ws/dm/{bob.id}/?token={alice_token}')
            self.assertTrue((await comm_alice.connect())[0])

            comm_bob = WebsocketCommunicator(application, f'/ws/dm/{alice.id}/?token={bob_token}')
            self.assertTrue((await comm_bob.connect())[0])

            await comm_alice.send_json_to({'message': 'hey bob, testing this'})
            received = await comm_bob.receive_json_from(timeout=5)
            self.assertEqual(received['body'], 'hey bob, testing this')

            await comm_alice.disconnect()
            await comm_bob.disconnect()

        async_to_sync(run)()

        self.assertEqual(
            Message.objects.filter(sender=alice, recipient=bob, body='hey bob, testing this').count(), 1,
            'message was broadcast over the socket but never persisted to the DB',
        )

        client = APIClient()
        client.force_authenticate(user=bob)
        resp = client.get('/api/chat/dm/')
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 1, f'conversation list is empty after a real message was sent: {rows}')
        self.assertEqual(rows[0]['user']['username'], 'alice_dm')
        self.assertEqual(rows[0]['last_message'], 'hey bob, testing this')

    def test_blocked_user_cannot_connect_to_dm(self):
        alice = User.objects.create_user(username='alice_block', email='alice_block@example.com', password='TestPass123!')
        bob = User.objects.create_user(username='bob_block', email='bob_block@example.com', password='TestPass123!')
        Block.objects.create(blocker=bob, blocked=alice)
        alice_token = str(AccessToken.for_user(alice))

        async def run():
            comm = WebsocketCommunicator(application, f'/ws/dm/{bob.id}/?token={alice_token}')
            connected, close_code = await comm.connect()
            self.assertFalse(connected)

        async_to_sync(run)()


class DMUnreadCountTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username='alice_unread', email='alice_unread@example.com', password='TestPass123!')
        self.bob = User.objects.create_user(username='bob_unread', email='bob_unread@example.com', password='TestPass123!')

    def test_unread_count_reflects_unread_messages(self):
        Message.objects.create(sender=self.alice, recipient=self.bob, body='hi')
        Message.objects.create(sender=self.alice, recipient=self.bob, body='still there?')

        self.client.force_authenticate(user=self.bob)
        resp = self.client.get('/api/chat/dm/unread-count/')
        self.assertEqual(resp.status_code, 200)
        # Two unread messages from the same person = 1 unread conversation.
        self.assertEqual(resp.json()['count'], 1)

    def test_reading_history_clears_unread(self):
        Message.objects.create(sender=self.alice, recipient=self.bob, body='hi')
        self.client.force_authenticate(user=self.bob)
        self.client.get(f'/api/chat/dm/{self.alice.id}/history/')
        resp = self.client.get('/api/chat/dm/unread-count/')
        self.assertEqual(resp.json()['count'], 0)
