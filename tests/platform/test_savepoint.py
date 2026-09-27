"""X11a: a named unique violation inside a savepoint is handled; any other re-raises."""

import itertools

import pytest
from django.db import IntegrityError, transaction

from commerce_core.platform.db.savepoint import (
    RetriesExhausted,
    on_unique_violation,
    retry_on_unique_violation,
)
from tests.testapp.models import UniqueProbe

pytestmark = pytest.mark.django_db

CODE = "testapp_uniqueprobe_code_uniq"


def test_named_violation_is_treated_as_replay_and_outer_transaction_survives():
    with transaction.atomic():
        original = UniqueProbe.objects.create(code="A", other="1")
        found = on_unique_violation(
            CODE,
            insert=lambda: UniqueProbe.objects.create(code="A", other="2"),
            on_violation=lambda: UniqueProbe.objects.get(code="A"),
        )
        assert found == original
        UniqueProbe.objects.create(code="B", other="3")  # outer transaction still usable
    assert UniqueProbe.objects.count() == 2


def test_named_violation_is_retried_with_a_new_value():
    UniqueProbe.objects.create(code="N-1", other="x")
    counter = itertools.count(1)
    probe = retry_on_unique_violation(
        CODE,
        lambda: UniqueProbe.objects.create(code=f"N-{next(counter)}", other=f"o{next(counter)}"),
    )
    assert probe.code != "N-1"


def test_other_constraint_reraises():
    UniqueProbe.objects.create(code="A", other="same")
    with pytest.raises(IntegrityError, match="testapp_uniqueprobe_other_uniq"):
        on_unique_violation(
            CODE,
            insert=lambda: UniqueProbe.objects.create(code="B", other="same"),
            on_violation=lambda: None,
        )


def test_retries_are_bounded():
    UniqueProbe.objects.create(code="fixed", other="x")
    with pytest.raises(RetriesExhausted):
        retry_on_unique_violation(
            CODE, lambda: UniqueProbe.objects.create(code="fixed", other="y"), attempts=3
        )
