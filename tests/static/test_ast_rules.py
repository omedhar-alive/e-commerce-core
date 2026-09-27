"""W8a: each static check catches its forbidden form, and core passes them all."""

import textwrap

import pytest
from tools.checks.ast_rules import check_source, check_tree


def _rules(source, path="commerce_core/x/module.py"):
    return sorted({v.rule for v in check_source(path, textwrap.dedent(source))})


def test_core_passes_every_static_check():
    assert [str(v) for v in check_tree()] == []


@pytest.mark.parametrize(
    "source, rule",
    [
        ("try:\n    f()\nexcept:\n    raise\n", "X1"),
        ("try:\n    f()\nexcept Exception:\n    log()\n", "X1"),
        ("try:\n    f()\nexcept KeyError:\n    pass\n", "X1"),
        ("import os\nx = os.environ['A']\n", "F1a"),
        ("from django.conf import settings\n", "F1a"),
        ("x.save()\n", "D7b"),
        ("order.payment_status = 'paid'\n", "S3"),
        ("variant.stock -= 1\n", "C9"),
        (
            "from commerce_core.platform.errors.exceptions import NotFound\nraise NotFound('no such order')\n",
            "L4",
        ),
        (
            "from django.db import transaction\nwith transaction.atomic():\n    try:\n        f()\n    except KeyError:\n        g()\n",
            "X11",
        ),
        (
            "from django.db import IntegrityError\ntry:\n    f()\nexcept IntegrityError:\n    raise\n",
            "X11a",
        ),
        ("ip = request.META['HTTP_X_FORWARDED_FOR']\n", "A9b"),
        ("import urllib.request\n", "T4"),
    ],
)
def test_each_rule_catches_its_form(source, rule):
    assert rule in _rules(source)


def test_models_may_not_read_settings():
    assert "D2f" in _rules(
        "from x import get_setting\nMAX = get_setting('A')\n", "commerce_core/x/models.py"
    )


def test_money_rules():
    src = """
    from django.db import models
    class Line(models.Model):
        price = models.IntegerField()
        weight = models.FloatField()
    class Paid(models.Model):
        amount = MoneyAmountField()
    """
    violations = check_source("commerce_core/x/models.py", textwrap.dedent(src))
    messages = {(v.rule, v.message.split()[0]) for v in violations}
    assert ("M1", "Line.price") in messages
    assert ("M1", "Line.weight") in messages
    assert ("M2", "Paid") in messages


def test_history_foreign_keys():
    src = "from django.db import models\nuser = models.ForeignKey('accounts.User', on_delete=models.CASCADE)\n"
    assert "O7" in _rules(src)
    ok = "from django.db import models\nuser = models.ForeignKey('accounts.User', on_delete=models.PROTECT)\n"
    assert "O7" not in _rules(ok)


def test_optional_returns_in_services():
    src = "def find(x) -> int | None:\n    return None\n"
    assert "X2" in _rules(src, "commerce_core/x/services.py")
    assert "X2" not in _rules(src, "commerce_core/x/queries.py")


@pytest.mark.parametrize(
    "source",
    [
        "x.save(update_fields=['a'])\n",
        "x.save(force_insert=True)\n",
        "def transition_to(order):\n    order.payment_status = 'paid'\n",
        "from django.db import transaction\ntry:\n    with transaction.atomic():\n        f()\nexcept KeyError:\n    raise\n",
    ],
)
def test_allowed_forms_pass(source):
    assert _rules(source) == []
