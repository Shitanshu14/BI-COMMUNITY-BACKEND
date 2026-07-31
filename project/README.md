# SETU Backend — Phase 0 (Bharat Intelligent)

Django + DRF + Channels backend for the SETU MVP (Feed | Chat | Members |
Activities | Resources). Covers the 5 MVP features from the master brief:

1. Signup/Login + Profile — `users` app
2. Community create/join/discovery — `communities` app
3. Feed: post + like + comment (Question/Knowledge types) — `posts` app
4. Real-time community chat — `chat` app (Django Channels, WebSocket)
5. Manual verification (admin-approved) — `verification` app

## Quick start (Week-1 setup)

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
4. Start a Celery worker for background jobs (notifications, later AI tasks):
   ```bash
   celery -A setu_backend worker -l info
   ```

## API surface (Phase 0/1)

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
| `/api/posts/?community=<id>` | GET/POST | Feed for a community |
| `/api/posts/<id>/like/` | POST | Toggle like |
| `/api/posts/<id>/comments/` | GET/POST | Comments |
| `/api/chat/<community_id>/history/` | GET | Last 50 chat messages |
| `ws://.../ws/chat/<community_id>/` | WS | Live chat (Channels) |
| `/api/verification/request/` | POST | Submit verification proof |
| `/api/verification/me/` | GET | Own verification status |

## App structure

```
setu_backend/     project settings, urls, asgi (Channels routing), celery.py
users/            custom User model (role, headline, is_verified, reputation)
communities/      Community, Membership (join/leave)
posts/            Post, Comment (feed, like, comment)
chat/             Message model + Channels consumer (real-time chat)
verification/     VerificationRequest + admin approve/reject actions
```

## Notes

- `AUTH_USER_MODEL` is custom (`users.User`) — this was set before the
  first migration, as required by Django.
- Chat currently has one room per community (matches the mockups' single
  "Chat" tab per community). 1:1 DMs can be added in Phase 2 by adding a
  `recipient` field and making `community` nullable on `Message`.
- Post types include `project`/`resource`/`poll` in the schema already so
  no migration is needed when those ship in Phase 2 — just expose them in
  the API/Flutter UI when ready.
- Naming: package is called `setu_backend` for now; rename is just a
  find-and-replace away once the final product name is locked.
