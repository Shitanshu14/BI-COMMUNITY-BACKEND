# BI Community Backend

Django + DRF + Channels backend for BI Community (Feed | Chat | Circles |
Members | Verification | Notifications | Follows).

1. Signup/Login + Profile — `users` app
2. Community create/join/discovery — `communities` app
3. Circles: small private invite-only groups with their own chat — `circles` app
4. Feed: post + like + comment + poll + question/solved — `posts` app
5. Real-time chat: per-community rooms, per-circle rooms, and 1:1 DMs — `chat` app (Django Channels, WebSocket)
6. Manual verification (admin-approved) — `verification` app
7. In-app notifications (bell icon), sent via Celery so requests don't wait on them — `notifications` app
8. Follow requests (public/private profile follow flow) — `follows` app

## Quick start

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # defaults to SQLite, zero config needed
python manage.py migrate
python manage.py createsuperuser  # for /admin/ — used for manual verification
python manage.py runserver
```

Visit `http://127.0.0.1:8000/admin/` to manage users, communities, posts,
and approve verification requests.

## Switching to real infra (Supabase Postgres + Redis)

1. In `.env`, set `USE_SQLITE=False` and fill in `DB_NAME`, `DB_USER`,
   `DB_PASSWORD`, `DB_HOST` from your Supabase project settings.
2. Install Redis locally (`brew install redis` / `apt install redis-server`)
   or point `REDIS_HOST`/`REDIS_PORT` at a hosted Redis (e.g. Upstash).
3. Run chat with Channels' dev server instead of plain `runserver`:
   ```bash
   pip install daphne
   daphne setu_backend.asgi:application
   ```
4. Start a Celery worker for background jobs (notifications, email tokens):
   ```bash
   celery -A setu_backend worker -l info
   ```

## API surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/users/register/` | POST | Signup |
| `/api/users/login/` | POST | Login (JWT access+refresh) |
| `/api/users/login/refresh/` | POST | Refresh JWT |
| `/api/users/me/` | GET/PATCH | Own profile |
| `/api/users/<id>/` | GET | Public profile |
| `/api/communities/` | GET/POST | Discover / create communities (search via `?search=`) |
| `/api/communities/<id>/join/` | POST | Join |
| `/api/communities/<id>/leave/` | POST | Leave |
| `/api/communities/<id>/members/` | GET | Member list |
| `/api/circles/` | GET/POST | Your circles / create a circle |
| `/api/circles/<id>/invite/` | POST | Invite a user by username |
| `/api/circles/<id>/leave/` | POST | Leave (owner deletes instead) |
| `/api/posts/?community=<id>` | GET/POST | Feed for a community |
| `/api/posts/<id>/like/` | POST | Toggle like |
| `/api/posts/<id>/mark_solved/` | POST | One-way: author marks a QUESTION post solved |
| `/api/posts/<id>/comments/` | GET/POST | Comments |
| `/api/chat/<community_id>/history/` | GET | Last 50 messages in a community room |
| `/api/chat/circle/<circle_id>/history/` | GET | Last 50 messages in a circle room |
| `/api/chat/dm/<user_id>/history/` | GET | 1:1 DM history |
| `ws://.../ws/chat/<community_id>/` | WS | Live community chat (Channels) |
| `ws://.../ws/chat/circle/<circle_id>/` | WS | Live circle chat (Channels) |
| `ws://.../ws/dm/<user_id>/` | WS | Live 1:1 DM (Channels) |
| `/api/verification/request/` | POST | Submit verification proof |
| `/api/verification/me/` | GET | Own verification status |
| `/api/notifications/` | GET | Own notifications |
| `/api/follow-requests/` | GET/POST | Follow request flow for private profiles |
| `/api/search/?q=...` | GET | Global search across users/posts/communities |

## App structure

```
setu_backend/     project settings, urls, asgi (Channels routing), celery.py
users/            custom User model (role, headline, is_verified, reputation)
communities/      Community, Membership (join/leave)
circles/          Circle, CircleMembership, CircleInvite (private groups + their chat)
posts/            Post, Comment, PollOption/PollVote, SavedPost (feed, like, comment, solve)
chat/             Message model (community/circle/DM) + Channels consumers (real-time)
verification/     VerificationRequest + admin approve/reject actions
notifications/    Notification model + Celery tasks that create them
follows/          Follow, follow-request accept/reject flow
```

## Notes

- `AUTH_USER_MODEL` is custom (`users.User`) — this was set before the
  first migration, as required by Django.
- `chat.Message` has three optional FKs — `community`, `circle`, `recipient`
  — exactly one is set per message depending on which room it's in; this is
  enforced in the consumers, not a DB constraint (see `chat/models.py`).
- Post types include `project`/`resource`/`poll`/`question` in the schema;
  `is_solved`/`solved_at` only apply to `question` posts.
- Naming: package is called `setu_backend` for now; rename is just a
  find-and-replace away once the final product name is locked.
- Before pushing model changes, run `python manage.py makemigrations --check
  --dry-run` — it should print "No changes detected". If it doesn't, a
  migration is missing and needs to be committed alongside the model change.

