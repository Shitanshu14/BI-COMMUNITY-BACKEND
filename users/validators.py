import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

class UniqueLettersAndSymbolsValidator:
    """
    Validates that the password contains at least one symbol/special character
    and at least a minimum number of unique characters.
    """
    def __init__(self, min_unique=5):
        self.min_unique = min_unique

    def validate(self, password, user=None):
        # Enforce at least one symbol (non-alphanumeric character)
        if not re.search(r'[^a-zA-Z0-9]', password):
            raise ValidationError(
                _("The password must contain at least one symbol (e.g. !, @, #, $, etc.)."),
                code='password_missing_symbol',
            )

        # Enforce unique characters count
        if len(set(password)) < self.min_unique:
            raise ValidationError(
                _("The password must contain at least %(min_unique)d unique characters."),
                code='password_too_few_unique',
                params={'min_unique': self.min_unique},
            )

    def get_help_text(self):
        return _(
            "Your password must contain at least one symbol and at least %(min_unique)d unique characters."
            % {'min_unique': self.min_unique}
        )
