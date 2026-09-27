"""Field types that normalize on every ORM write, including ``QuerySet.update()``."""

from django.db import models

from commerce_core.accounts.normalize import normalize_email, normalize_phone


class NormalizedEmailField(models.EmailField):
    """Stored normalized (A1a). Lookups normalize too, so ``email=`` filters match."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return normalize_email(value) if value else value

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)
        if value:
            value = normalize_email(value)
            setattr(model_instance, self.attname, value)
        return value


class PhoneField(models.CharField):
    """Stored as E.164; an invalid number raises ``validation_error`` on write."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 16)
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return normalize_phone(value, field=self.name) if value else value

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)
        if value:
            value = normalize_phone(value, field=self.name)
            setattr(model_instance, self.attname, value)
        return value
