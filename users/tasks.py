import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator, PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger('setu_backend')


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Separate token generator (different hash salt) from the password-reset
    one, so a leaked email-verification link can't be replayed to reset a
    password and vice versa."""

    def _make_hash_value(self, user, timestamp):
        return f'{user.pk}{timestamp}{user.email_confirmed}'


email_verification_token = EmailVerificationTokenGenerator()


@shared_task
def send_verification_email(user_id):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning('send_verification_email: user %s does not exist', user_id)
        return

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    link = f'{settings.FRONTEND_URL}/verify-email?uid={uid}&token={token}'

    send_mail(
        subject='Confirm your SETU account',
        message=f'Hi {user.username},\n\nConfirm your email to activate your SETU account:\n{link}\n\nIf you did not sign up, ignore this email.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


@shared_task
def send_password_reset_email(user_id):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning('send_password_reset_email: user %s does not exist', user_id)
        return

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f'{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}'

    send_mail(
        subject='Reset your SETU password',
        message=f'Hi {user.username},\n\nReset your password here:\n{link}\n\nIf you did not request this, ignore this email — your password will not change.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
