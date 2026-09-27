"""A1: the custom user model was set before the first migration.

Owner ruling C4: accounts.0001 is the first core migration, depends only on
django.contrib apps, and every other commerce_core migration depends on it
directly or indirectly.
"""

from django.conf import settings
from django.db.migrations.loader import MigrationLoader

ROOT = ("accounts", "0001_initial")


def _core_apps():
    from django.apps import apps

    return {c.label for c in apps.get_app_configs() if c.name.startswith("commerce_core.")}


def _contrib_apps():
    from django.apps import apps

    return {c.label for c in apps.get_app_configs() if c.name.startswith("django.contrib.")}


def test_auth_user_model_is_set():
    assert settings.AUTH_USER_MODEL == "accounts.User"


def test_accounts_0001_depends_only_on_contrib():
    graph = MigrationLoader(None, ignore_no_migrations=True).graph
    parents = graph.node_map[ROOT].parents
    assert parents
    assert {p.key[0] for p in parents} <= _contrib_apps()


def test_accounts_0001_is_first_core_migration_and_every_other_descends_from_it():
    graph = MigrationLoader(None, ignore_no_migrations=True).graph
    core = _core_apps()
    for key in graph.nodes:
        if key[0] in core and key != ROOT:
            assert ROOT in graph.forwards_plan(key), key
    ancestors = set(graph.forwards_plan(ROOT)) - {ROOT}
    assert not {k for k in ancestors if k[0] in core}
