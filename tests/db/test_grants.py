"""D7, D7a, D7b: protected tables refuse what their grants do not list."""

import pytest
from django.db import connection, models, transaction
from django.db.utils import ProgrammingError
from psycopg import errors

from commerce_core.platform.db import roles
from commerce_core.platform.db.governed import BareSaveOnGovernedModel, governed_models
from tests.testapp.models import GovernedProbe

pytestmark = pytest.mark.django_db


def _has(sql_expr: str, params) -> bool:
    with connection.cursor() as cur:
        cur.execute(f"SELECT {sql_expr}", params)
        return cur.fetchone()[0]


def _updatable_columns(model, role: str) -> set[str]:
    table = model._meta.db_table
    return {
        f.column
        for f in model._meta.concrete_fields
        if _has("has_column_privilege(%s, %s, %s, 'UPDATE')", [role, table, f.column])
    }


def _table_privilege(table: str, role: str, privilege: str) -> bool:
    return _has("has_table_privilege(%s, %s, %s)", [role, table, privilege])


@pytest.mark.parametrize("role", roles.DML_ROLES)
def test_append_only_refuses_update_and_delete(role_conn, role):
    conn = role_conn(role)
    conn.execute("INSERT INTO testapp_appendonlyprobe (note) VALUES ('committed')")
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute("UPDATE testapp_appendonlyprobe SET note = 'changed'")
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute("DELETE FROM testapp_appendonlyprobe")


@pytest.mark.parametrize("role", roles.DML_ROLES)
def test_frozen_table_allows_only_listed_columns(role_conn, role):
    conn = role_conn(role)
    conn.execute("INSERT INTO testapp_governedprobe (amount, status) VALUES (100, 'a')")
    conn.execute("UPDATE testapp_governedprobe SET status = 'b'")
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute("UPDATE testapp_governedprobe SET amount = 1")


def test_bare_save_is_refused_before_sql():
    probe = GovernedProbe.objects.create(amount=5, status="a")
    probe.status = "b"
    with pytest.raises(BareSaveOnGovernedModel):
        probe.save()


def test_bare_save_is_refused_by_the_database_too():
    """Bypass the model guard: the grant alone still refuses a full-row save."""
    probe = GovernedProbe.objects.create(amount=5, status="a")
    probe.status = "b"
    with pytest.raises(ProgrammingError, match="permission denied"):
        with transaction.atomic():
            models.Model.save(probe)  # skips GovernedModel.save


def test_named_columns_save_works():
    probe = GovernedProbe.objects.create(amount=5, status="a")
    probe.status = "b"
    probe.save(update_fields=["status"])
    GovernedProbe.objects.filter(pk=probe.pk).update(status="c")
    probe.refresh_from_db()
    assert probe.status == "c"


def test_declared_governance_matches_database_grants():
    assert governed_models(), "no governed models registered"
    for model in governed_models():
        table = model._meta.db_table
        declared = {model._meta.get_field(f).column for f in model.GOVERNANCE.update_fields}
        for role in roles.DML_ROLES:
            assert _updatable_columns(model, role) == declared, (table, role)
            assert not _table_privilege(table, role, "UPDATE"), (table, role)
            deletable = _table_privilege(table, role, "DELETE")
            assert deletable == model.GOVERNANCE.allow_delete, (table, role)
            assert not _table_privilege(table, role, "TRUNCATE"), (table, role)


def test_no_auto_now_on_governed_models_unless_updatable():
    for model in governed_models():
        for field in model._meta.concrete_fields:
            if getattr(field, "auto_now", False):
                assert field.name in model.GOVERNANCE.update_fields, (model, field.name)
