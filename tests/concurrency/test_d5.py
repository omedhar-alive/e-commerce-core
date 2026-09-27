"""D5: every uniqueness row in phase 1 has a concurrency test on real connections."""

import pytest
from django.db import IntegrityError

from commerce_core.accounts.models import User
from tests.concurrency.helpers import run_concurrently

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.concurrency]


def test_email_concurrent_insert_one_wins():
    def register(email):
        def work(barrier):
            user = User(email=email)
            user.set_unusable_password()
            barrier.wait()
            user.save(force_insert=True)
            return user.pk

        return work

    outcomes = run_concurrently(register("Race@x.com"), register("race@X.com"))
    winners = [r for r, e in outcomes if e is None]
    losers = [e for r, e in outcomes if e is not None]
    assert len(winners) == 1
    assert len(losers) == 1 and isinstance(losers[0], IntegrityError)
    assert "accounts_user_email_ci_uniq" in str(losers[0])
    assert User.objects.filter(email="race@x.com").count() == 1


def test_runtimesetting_unique_nulls_not_distinct():
    from commerce_core.platform.models import RuntimeSetting

    RuntimeSetting.objects.all().delete()

    def insert(barrier):
        barrier.wait()
        return RuntimeSetting.objects.create(kind="checkout_kill_switch", enabled=False).pk

    outcomes = run_concurrently(insert, insert)
    assert sum(1 for r, e in outcomes if e is None) == 1
    loser = next(e for r, e in outcomes if e is not None)
    assert isinstance(loser, IntegrityError)
    assert "runtimesetting_kind_provider_uniq" in str(loser)
