import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """
    Creates (or updates the password of) a superuser from environment
    variables, without ever prompting for input.

    Safe to run on every deploy: if the user already exists it just makes
    sure the password matches the env var and moves on, instead of
    crashing the build like `createsuperuser --noinput` does on a repeat run.

    Needs these env vars set on Render:
      DJANGO_SUPERUSER_EMAIL
      DJANGO_SUPERUSER_PASSWORD
      DJANGO_SUPERUSER_USERNAME   (optional, defaults to 'admin')
    """

    help = 'Create a default superuser from env vars if one does not already exist'

    def handle(self, *args, **options):
        User = get_user_model()

        email = os.environ.get('DJANGO_SUPERUSER_EMAIL')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')

        if not email or not password:
            self.stdout.write(self.style.WARNING(
                'DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD not set — skipping superuser creation.'
            ))
            return

        user, created = User.objects.get_or_create(
            email=email,
            defaults={'username': username, 'is_staff': True, 'is_superuser': True},
        )

        user.username = username
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f'Created superuser: {email}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Superuser already existed, password synced: {email}'))
