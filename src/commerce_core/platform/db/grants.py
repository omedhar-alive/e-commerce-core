"""Grant helpers that protect a table, used by the migration that creates it.

D7: append-only tables. Web and job lose ``UPDATE`` and ``DELETE``, and get
``UPDATE`` back only on the columns their lifecycle writes.
D7a: committed rows freeze their financial and copied columns the same way.

A column grant is checked against the ``SET`` list whatever the values are,
so every write to a protected table must name its columns (D7b). The model
side of that is ``commerce_core.platform.db.governed``.

``ProtectTable`` resolves table and column names from the migration's own
historical state, so it never imports a model (D2d).
"""

from django.db import migrations
from psycopg import sql

from commerce_core.platform.db import roles


def _dml_roles() -> sql.Composable:
    return sql.SQL(", ").join(sql.Identifier(r) for r in roles.DML_ROLES)


def protect_statements(
    table: str, *, update_columns: tuple[str, ...] = (), allow_delete: bool = False
) -> list[sql.Composed]:
    tbl = sql.Identifier(table)
    stmts = [
        sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON {} FROM {}").format(tbl, _dml_roles()),
    ]
    if update_columns:
        cols = sql.SQL(", ").join(sql.Identifier(c) for c in update_columns)
        stmts.append(sql.SQL("GRANT UPDATE ({}) ON {} TO {}").format(cols, tbl, _dml_roles()))
    if allow_delete:
        stmts.append(sql.SQL("GRANT DELETE ON {} TO {}").format(tbl, _dml_roles()))
    return stmts


def unprotect_statements(table: str) -> list[sql.Composed]:
    tbl = sql.Identifier(table)
    return [sql.SQL("GRANT UPDATE, DELETE ON {} TO {}").format(tbl, _dml_roles())]


class ProtectTable(migrations.operations.base.Operation):
    """Apply D7/D7a grants to a model's table, from historical state.

    ``update_fields`` are model field names; they are resolved to columns.
    """

    reduces_to_sql = True
    reversible = True

    def __init__(self, model_name: str, update_fields=(), allow_delete: bool = False):
        self.model_name = model_name
        self.update_fields = tuple(update_fields)
        self.allow_delete = allow_delete

    def deconstruct(self):
        kwargs = {"model_name": self.model_name}
        if self.update_fields:
            kwargs["update_fields"] = self.update_fields
        if self.allow_delete:
            kwargs["allow_delete"] = self.allow_delete
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, app_label, state):
        pass

    def _resolve(self, app_label, state):
        model = state.apps.get_model(app_label, self.model_name)
        columns = tuple(model._meta.get_field(f).column for f in self.update_fields)
        return model._meta.db_table, columns

    def _run(self, schema_editor, statements):
        conn = schema_editor.connection
        for stmt in statements:
            schema_editor.execute(stmt.as_string(conn.connection))

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        table, columns = self._resolve(app_label, to_state)
        self._run(
            schema_editor,
            protect_statements(table, update_columns=columns, allow_delete=self.allow_delete),
        )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        table, _ = self._resolve(app_label, from_state)
        self._run(schema_editor, unprotect_statements(table))

    def describe(self):
        return f"Protect table of {self.model_name} (D7/D7a grants)"

    @property
    def migration_name_fragment(self):
        return f"protect_{self.model_name.lower()}"
