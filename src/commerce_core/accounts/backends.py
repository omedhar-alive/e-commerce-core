"""Authentication backend for the email-based user (A1, A1a).

Uniqueness of ``User.email`` is the case-insensitive functional index
``accounts_user_email_ci_uniq``, not a plain ``unique=True``, so Django's
auth.W004 warning is silenced by the settings builder. Lookups go through
``normalize_email`` via the manager.
"""

from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    pass
