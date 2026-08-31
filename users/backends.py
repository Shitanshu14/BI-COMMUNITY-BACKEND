from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

class EmailOrUsernameModelBackend(ModelBackend):
    """
    Custom authentication backend that allows users to log in using
    either their email or username case-insensitively.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None:
            # SimpleJWT or other libraries might pass the username under the model's USERNAME_FIELD keyword (email)
            username = kwargs.get('email') or kwargs.get('username') or kwargs.get(User.USERNAME_FIELD)

        if username is None:
            return None

        try:
            # Query by email or username case-insensitively
            user = User.objects.get(Q(email__iexact=username) | Q(username__iexact=username))
        except User.DoesNotExist:
            # Run the default password hasher once to reduce timing differences
            User().set_password(password)
            return None
        else:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
