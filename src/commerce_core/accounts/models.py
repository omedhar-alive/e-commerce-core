"""The custom user model, set before the first migration and never swapped (A1)."""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from commerce_core.accounts.fields import NormalizedEmailField, PhoneField
from commerce_core.accounts.normalize import normalize_email
from commerce_core.accounts.permissions import PERMISSIONS


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, email):
        return self.get(email=normalize_email(email))

    def create_user(self, email, password=None, **extra_fields):
        user = self.model(email=normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db, force_insert=True)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.update(is_staff=True, is_superuser=True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = NormalizedEmailField(max_length=254)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = PhoneField(null=True, blank=True, db_index=True)
    # ISO 3166-1 alpha-2 and a language code: plain columns validated against
    # the registry, never DB choices (D2f).
    country = models.CharField(max_length=2, blank=True)
    preferred_language = models.CharField(max_length=15, blank=True)
    # A4b: every credential names the version it was issued under.
    token_version = models.PositiveIntegerField(db_default=0, editable=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_uniq"),
        ]

    def __str__(self):
        return f"User {self.pk}"


class CorePermissions(models.Model):
    """Holds the A6a permissions. Unmanaged: no table, never queried."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = list(PERMISSIONS.items())

    def __str__(self):
        return "Core permissions"
