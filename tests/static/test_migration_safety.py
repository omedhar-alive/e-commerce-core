"""D2, D2b, D2c, D3: the classifier rejects blocking forms on existing tables and flags destructive ones."""

import pytest
from django.contrib.postgres.operations import AddConstraintNotValid, AddIndexConcurrently
from django.db import migrations, models
from django.db.migrations.loader import MigrationLoader

from commerce_core.platform.release.safety import classify, classify_operations

EXISTING = frozenset({"testapp_pageprobe"})


@pytest.fixture
def state():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    return loader.project_state(("testapp", "0004_probes"), at_end=True)


def _kinds(ops, state, existing=EXISTING, atomic=True, name="0099_x"):
    return [
        (f.kind, f.detail)
        for f in classify_operations("testapp", name, ops, state, existing, atomic=atomic)
    ]


def _index():
    return models.Index(fields=["owner"], name="pageprobe_owner")


def test_rejects_plain_index_on_existing_table(state):
    kinds = _kinds([migrations.AddIndex("pageprobe", _index())], state)
    assert kinds and kinds[0][0] == "blocking"


def test_accepts_concurrent_index_in_non_atomic_migration(state):
    assert _kinds([AddIndexConcurrently("pageprobe", _index())], state, atomic=False) == []


def test_concurrent_index_needs_atomic_false(state):
    assert (
        _kinds([AddIndexConcurrently("pageprobe", _index())], state, atomic=True)[0][0]
        == "blocking"
    )


def test_rejects_validated_check_constraint_on_existing_table(state):
    check = models.CheckConstraint(condition=models.Q(owner__gt=""), name="pageprobe_owner_set")
    assert _kinds([migrations.AddConstraint("pageprobe", check)], state)[0][0] == "blocking"
    assert _kinds([AddConstraintNotValid("pageprobe", check)], state) == []


def test_new_table_may_use_plain_forms(state):
    assert _kinds([migrations.AddIndex("pageprobe", _index())], state, existing=frozenset()) == []


def test_not_null_column_without_db_default_is_unsafe(state):
    ops = [migrations.AddField("pageprobe", "flag", models.BooleanField(default=False))]
    assert "unsafe" in {k for k, _ in _kinds(ops, state)}
    ok = [migrations.AddField("pageprobe", "flag", models.BooleanField(db_default=False))]
    assert _kinds(ok, state) == []


def test_flags_drop_column_and_table_as_destructive(state):
    assert _kinds([migrations.RemoveField("pageprobe", "category")], state)[0][0] == "destructive"
    assert _kinds([migrations.DeleteModel("pageprobe")], state)[0][0] == "destructive"


def test_flags_type_change_as_destructive(state):
    ops = [migrations.AlterField("pageprobe", "name", models.CharField(max_length=10))]
    assert "destructive" in {k for k, _ in _kinds(ops, state)}


def test_rename_in_place_is_unsafe(state):
    assert _kinds([migrations.RenameField("pageprobe", "name", "title")], state)[0][0] == "unsafe"


def test_runsql_rewrite_is_destructive_but_revoke_is_not(state):
    assert (
        _kinds([migrations.RunSQL("UPDATE testapp_pageprobe SET name = ''")], state)[0][0]
        == "destructive"
    )
    assert _kinds([migrations.RunSQL("REVOKE UPDATE, DELETE, TRUNCATE ON t FROM r")], state) == []


def test_runpython_outside_allowlist_is_rejected(state):
    op = migrations.RunPython(migrations.RunPython.noop)
    assert _kinds([op], state)[0][0] == "runpython"


def test_every_shipped_core_migration_passes():
    from django.apps import apps

    loader = MigrationLoader(None, ignore_no_migrations=True)
    core = {c.label for c in apps.get_app_configs() if c.name.startswith("commerce_core.")}
    keys = [k for k in loader.graph.nodes if k[0] in core]
    keys.sort(key=lambda k: len(loader.graph.forwards_plan(k)))
    findings = classify(loader, keys, frozenset())
    assert [f for f in findings if f.kind in {"blocking", "unsafe", "runpython"}] == []
