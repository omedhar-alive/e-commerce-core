"""Migration safety classifier (D2, D2b, D2c, D3).

Reads migration operations, not SQL, and reports:

* ``blocking``: an index or constraint built the blocking way on a table that
  already existed in the previous release (D2b). Indexes must be
  ``AddIndexConcurrently`` in an ``atomic = False`` migration; CHECK and
  foreign-key constraints are added ``NOT VALID`` and validated separately;
  unique constraints start as a concurrent unique index.
* ``unsafe``: a change the running code cannot survive (D2): an in-place
  rename, or a ``NOT NULL`` column added without a constant ``db_default``.
* ``destructive``: drops a column or table that already exists, changes an
  existing column's type, or rewrites values (D3). The release step refuses
  these without a restore point. A table created earlier in the same run
  holds no data yet, so dropping from it is not destructive.
* ``runpython``: ``RunPython`` outside the seed allowlist (D2c).

The same classifier runs in CI (``tools/checks/migration_safety.py``) and in
the release step.
"""

import re
from dataclasses import dataclass

from django.contrib.postgres.operations import (
    AddConstraintNotValid,
    AddIndexConcurrently,
    RemoveIndexConcurrently,
    ValidateConstraint,
)
from django.db import connection, migrations, models
from django.db.migrations.state import ProjectState

# D2c: migrations allowed to use RunPython (seed and lookup rows only).
RUNPYTHON_ALLOWLIST = frozenset(
    {
        ("accounts", "0003_seed_groups"),
        ("platform", "0001_initial"),
    }
)

_DESTRUCTIVE_SQL = re.compile(
    r"\b(DROP\s+(TABLE|COLUMN)|ALTER\s+COLUMN\s+\S+\s+(SET\s+DATA\s+)?TYPE|UPDATE\s+\S+\s+SET|"
    r"DELETE\s+FROM|TRUNCATE\s+(TABLE\s+)?(?!ON\b)\w)",
    re.IGNORECASE,
)
_BLOCKING_SQL = re.compile(r"\bCREATE\s+(UNIQUE\s+)?INDEX\b(?!\s+CONCURRENTLY)", re.IGNORECASE)
_CONSTRAINT_SQL = re.compile(r"\bADD\s+CONSTRAINT\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    app_label: str
    migration: str
    kind: str  # blocking | unsafe | destructive | runpython
    detail: str

    def __str__(self):
        return f"{self.app_label}.{self.migration}: {self.kind}: {self.detail}"


def _table(state: ProjectState, app_label: str, model_name: str) -> str | None:
    model_state = state.models.get((app_label, model_name.lower()))
    if model_state is None:
        return None
    return model_state.options.get("db_table") or f"{app_label}_{model_name.lower()}"


def _sql_text(sql) -> str:
    if isinstance(sql, (list, tuple)):
        return " ".join(_sql_text(s) for s in sql)
    return str(sql)


def _column_type(state: ProjectState, app_label: str, model_name: str, field_name: str):
    model_state = state.models[(app_label, model_name.lower())]
    return model_state.fields[field_name].db_type(connection)


def classify_operations(
    app_label: str,
    name: str,
    operations,
    state: ProjectState,
    existing_tables: frozenset[str],
    *,
    atomic: bool = True,
) -> list[Finding]:
    findings: list[Finding] = []

    def add(kind, detail):
        findings.append(Finding(app_label, name, kind, detail))

    for op in operations:
        on_existing = False
        model_name = getattr(op, "model_name", None) or getattr(op, "name", None)
        if model_name and isinstance(model_name, str):
            on_existing = _table(state, app_label, model_name) in existing_tables

        if isinstance(op, (AddIndexConcurrently, RemoveIndexConcurrently)):
            if atomic:
                add("blocking", f"{type(op).__name__} needs atomic = False")
        elif isinstance(op, (AddConstraintNotValid, ValidateConstraint)):
            pass
        elif isinstance(op, migrations.AddIndex) and on_existing:
            add("blocking", f"AddIndex {op.index.name} on existing table; use AddIndexConcurrently")
        elif isinstance(op, migrations.RemoveIndex) and on_existing:
            add("blocking", f"RemoveIndex {op.name} on existing table; use RemoveIndexConcurrently")
        elif isinstance(op, migrations.AddConstraint) and on_existing:
            add(
                "blocking",
                f"AddConstraint {op.constraint.name} validates under a strong lock; add it NOT VALID",
            )
        elif (
            isinstance(op, (migrations.AlterUniqueTogether, migrations.AlterIndexTogether))
            and on_existing
        ):
            add("blocking", f"{type(op).__name__} on existing table")
        elif isinstance(op, migrations.AddField):
            field = op.field
            if on_existing:
                if (
                    not field.null
                    and field.db_default is models.NOT_PROVIDED
                    and not field.many_to_many
                ):
                    add("unsafe", f"AddField {op.name} NOT NULL without a constant db_default (D2)")
                if (
                    field.db_index
                    or field.unique
                    or (field.is_relation and field.db_constraint and not field.many_to_many)
                ):
                    add(
                        "blocking",
                        f"AddField {op.name} builds an index or constraint on an existing table",
                    )
        elif isinstance(op, migrations.AlterField):
            if on_existing:
                before = _column_type(state, app_label, op.model_name, op.name)
                after = op.field.db_type(connection)
                if before != after:
                    add(
                        "destructive",
                        f"AlterField {op.model_name}.{op.name} changes type {before} -> {after}",
                    )
                if op.field.db_index or op.field.unique:
                    add(
                        "blocking",
                        f"AlterField {op.model_name}.{op.name} may build an index on an existing table",
                    )
        elif isinstance(op, migrations.RemoveField):
            if on_existing:
                add("destructive", f"RemoveField {op.model_name}.{op.name}")
        elif isinstance(op, migrations.DeleteModel):
            if on_existing:
                add("destructive", f"DeleteModel {op.name}")
        elif isinstance(op, (migrations.RenameField, migrations.RenameModel)):
            add("unsafe", f"{type(op).__name__} renames in place; use expand/contract (D2)")
        elif isinstance(op, migrations.RunPython):
            if (app_label, name) not in RUNPYTHON_ALLOWLIST:
                add("runpython", "RunPython outside the seed allowlist; backfills are jobs (D2c)")
        elif isinstance(op, migrations.RunSQL):
            text = _sql_text(op.sql)
            if _DESTRUCTIVE_SQL.search(text):
                add("destructive", "RunSQL drops, retypes or rewrites data")
            if _BLOCKING_SQL.search(text):
                add("blocking", "RunSQL creates an index without CONCURRENTLY")
            if _CONSTRAINT_SQL.search(text) and "NOT VALID" not in text.upper():
                add("blocking", "RunSQL adds a constraint without NOT VALID")
        elif isinstance(op, migrations.SeparateDatabaseAndState):
            findings.extend(
                classify_operations(
                    app_label, name, op.database_operations, state, existing_tables, atomic=atomic
                )
            )
        op.state_forwards(app_label, state)
    return findings


def classify(loader, keys, existing_tables: frozenset[str]) -> list[Finding]:
    """Classify migrations ``keys`` (in graph order) against the tables that already exist."""
    findings: list[Finding] = []
    for key in keys:
        migration = loader.graph.nodes[key]
        state = loader.project_state(key, at_end=False)
        findings.extend(
            classify_operations(
                key[0],
                key[1],
                migration.operations,
                state,
                existing_tables,
                atomic=migration.atomic,
            )
        )
    return findings


def tables_created_by(loader, keys) -> frozenset[str]:
    """Tables that exist once ``keys`` (and their dependencies) are applied."""
    if not keys:
        return frozenset()
    state = loader.project_state(list(keys), at_end=True)
    return frozenset(
        model.options.get("db_table") or f"{app}_{name}"
        for (app, name), model in state.models.items()
        if model.options.get("managed", True)
    )
