"""
Celery app for background jobs: notifications, AI processing (Phase 2),
verification-related async work. Broker/backend = Redis (see settings.py).
"""

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'setu_backend.settings')

app = Celery('setu_backend')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
