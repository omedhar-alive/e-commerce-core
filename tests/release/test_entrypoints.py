"""Decision 23 and D2g: each process reads only its own role's URL; no entry point migrates."""

import ast
import inspect
from collections.abc import Mapping
from pathlib import Path

import pytest

import commerce_core
from commerce_core.platform.conf import boot, process
from commerce_core.platform.conf.registry import Role
from tests.settings import TEST_ENV

URLS = {
    "WEB_DATABASE_URL": "postgresql://w:p@h/db",
    "JOB_DATABASE_URL": "postgresql://j:p@h/db",
    "MIGRATION_DATABASE_URL": "postgresql://m:p@h/db",
}


class SpyEnv(Mapping):
    def __init__(self, data):
        self.data = data
        self.read = set()

    def __getitem__(self, key):
        self.read.add(key)
        return self.data[key]

    def get(self, key, default=None):
        self.read.add(key)
        return self.data.get(key, default)

    def __iter__(self):
        raise AssertionError("the loader must not enumerate the environment")

    def __len__(self):
        return len(self.data)


def _read_urls(role):
    env = SpyEnv({**TEST_ENV, **URLS, "ALLOWED_HOSTS": "x.test"})
    boot.load(role, env)
    return {k for k in env.read if k.endswith("_DATABASE_URL")}


@pytest.mark.parametrize(
    "role, url",
    [
        (Role.WEB, "WEB_DATABASE_URL"),
        (Role.JOB, "JOB_DATABASE_URL"),
        (Role.MIGRATION, "MIGRATION_DATABASE_URL"),
    ],
)
def test_each_process_reads_only_its_role_url(role, url):
    assert _read_urls(role) == {url}


@pytest.mark.parametrize("role", [Role.WEB, Role.JOB])
def test_runtime_entrypoints_never_read_migration_url(role):
    assert "MIGRATION_DATABASE_URL" not in _read_urls(role)


def test_command_roles_follow_the_owner_ruling():
    assert process.COMMAND_ROLE == {
        "release": Role.MIGRATION,
        "create_staff": Role.WEB,
        "seed_demo": Role.JOB,
        "run_worker": Role.JOB,
        "run_scheduler": Role.JOB,
    }


@pytest.mark.parametrize(
    "argv, role",
    [
        (["manage.py", "run_worker"], Role.JOB),
        (["manage.py", "run_scheduler"], Role.JOB),
        (["manage.py", "release"], Role.MIGRATION),
        (["manage.py", "migrate"], None),
        (["manage.py", "shell"], None),
        (["gunicorn", "deployment.wsgi"], None),
    ],
)
def test_detect_role_from_command(argv, role):
    assert process.detect_role(argv) == role


def test_wsgi_entrypoint_declares_web(monkeypatch):
    from commerce_core import entrypoints

    monkeypatch.setattr("django.core.wsgi.get_wsgi_application", lambda: "app")
    monkeypatch.setattr(entrypoints, "run_startup_checks", lambda: None)
    monkeypatch.setattr(process, "_explicit", process._UNSET)
    assert entrypoints.wsgi_application() == "app"
    assert process.detect_role(["gunicorn"]) == Role.WEB
    monkeypatch.setattr(process, "_explicit", process._UNSET)


def test_no_process_entry_point_runs_migrate():
    """D2g: no core module outside the release step calls migrate."""
    root = Path(inspect.getfile(commerce_core)).parent
    offenders = []
    for path in root.rglob("*.py"):
        if "release" in path.parts or path.name == "release.py" or "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", "")) == "call_command"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "migrate"
            ):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []
