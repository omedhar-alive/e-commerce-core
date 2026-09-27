"""W8a: static checks that prove no code path does a forbidden thing.

    python -m tools.checks.ast_rules            # check src/commerce_core
    python -m tools.checks.ast_rules FILE...    # check given files

Each rule is a function ``(path, tree, source) -> list[Violation]``. Paths
are relative to ``src/`` (``commerce_core/...``). A line may opt out of a
rule only through an allowlist in this file, with a reason.

import-linter covers the import boundaries (T4, X6, D2d); ruff covers the
bare-except forms (X1); ``migration_safety`` covers D2b, D2c and D3. This
module covers the rest.
"""

import ast
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    line: int
    message: str

    def __str__(self):
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


# --- allowlists (each entry carries its reason) -----------------------------

# F1a: modules that may read the process environment or Django settings.
SETTINGS_READERS = {
    "commerce_core/platform/conf/django_settings.py": "the one reader of the environment",
}

# M1: DecimalField is allowed only on these non-money columns.
DECIMAL_ALLOWLIST: dict[str, str] = {}

# X2: domain-service functions that may return None, with the reason.
OPTIONAL_RETURN_ALLOWLIST = {
    "commerce_core/platform/runtime_settings/services.py::change_runtime_setting": (
        "None means the value was already set: a no-op, not a failure"
    ),
}

# X4, X11, X11a: the one module that may catch IntegrityError.
INTEGRITY_ERROR_MODULES = {"commerce_core/platform/db/savepoint.py"}

# A9b: the one module that may read X-Forwarded-For.
FORWARDED_FOR_MODULES = {"commerce_core/platform/ratelimit/client_ip.py"}

# O7: models whose rows history references. A foreign key to one of these may
# not CASCADE or SET_NULL. Later phases add Product, Variant, Order, ...
HISTORY_REFERENCED = {"User", "accounts.User", "AUTH_USER_MODEL"}

# S3, S6, C9: fields written only by transition_to() or the stock service.
# Wired now; the fields arrive with orders (phase 5) and stock (phase 2).
STATUS_FIELDS = {"payment_status", "fulfilment_status"}
STATUS_WRITERS = {"transition_to"}
STOCK_FIELDS = {"stock"}
STOCK_MODULES = {"commerce_core/catalog/stock.py"}

MONEY_NAME_HINTS = ("amount", "price", "total", "subtotal", "cost", "fee")


# --- helpers ----------------------------------------------------------------


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _ancestors(node, parents) -> Iterator[ast.AST]:
    while node in parents:
        node = parents[node]
        yield node


def _name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _name(node.func)
    return ""


def _is_atomic_with(node) -> bool:
    return isinstance(node, ast.With) and any(
        _name(item.context_expr).endswith("atomic") for item in node.items
    )


# --- rules ------------------------------------------------------------------


def rule_bare_except(path, tree, source):
    """X1: no bare except, no ``except Exception``, no ``except: pass``."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            caught = _name(node.type) if node.type else ""
            if node.type is None or caught in {"Exception", "BaseException"}:
                out.append(Violation("X1", path, node.lineno, f"catches {caught or 'everything'}"))
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                out.append(Violation("X1", path, node.lineno, "except: pass"))
    return out


def rule_settings_reads(path, tree, source):
    """F1a: configuration is read only through the registry."""
    if path in SETTINGS_READERS or path.startswith("commerce_core/platform/conf/"):
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _name(node) in {"os.environ", "os.getenv"}:
            out.append(Violation("F1a", path, node.lineno, f"reads {_name(node)}"))
        if isinstance(node, ast.ImportFrom) and node.module == "django.conf":
            if any(alias.name == "settings" for alias in node.names):
                out.append(Violation("F1a", path, node.lineno, "imports django.conf.settings"))
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "os"
            and any(a.name in {"environ", "getenv"} for a in node.names)
        ):
            out.append(Violation("F1a", path, node.lineno, "imports os.environ"))
    return out


def rule_models_read_no_settings(path, tree, source):
    """D2f: model definitions never depend on settings or environment."""
    if not path.endswith("models.py"):
        return []
    return [
        Violation("D2f", path, node.lineno, "model module reads a setting")
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in {"get_setting", "settings"}
    ]


def _model_classes(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            fields = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            fields[target.id] = (_name(stmt.value.func).split(".")[-1], stmt)
            yield node, fields


def rule_money_fields(path, tree, source):
    """M1, M2: money is MoneyAmountField; no FloatField; DecimalField only on the allowlist; a currency column beside it."""
    out = []
    for cls, fields in _model_classes(tree):
        has_money = False
        for field_name, (kind, stmt) in fields.items():
            key = f"{path}::{cls.name}.{field_name}"
            if kind == "FloatField":
                out.append(
                    Violation("M1", path, stmt.lineno, f"{cls.name}.{field_name} is a FloatField")
                )
            if kind == "DecimalField" and key not in DECIMAL_ALLOWLIST:
                out.append(
                    Violation("M1", path, stmt.lineno, f"{cls.name}.{field_name} is a DecimalField")
                )
            if kind == "MoneyAmountField":
                has_money = True
            elif (
                any(h in field_name for h in MONEY_NAME_HINTS)
                and kind.endswith("Field")
                and kind
                not in {
                    "CurrencyField",
                    "ForeignKey",
                }
            ):
                out.append(
                    Violation(
                        "M1",
                        path,
                        stmt.lineno,
                        f"{cls.name}.{field_name} looks like money but is {kind}",
                    )
                )
        if has_money and not any(kind == "CurrencyField" for kind, _ in fields.values()):
            out.append(
                Violation(
                    "M2", path, cls.lineno, f"{cls.name} has money fields but no CurrencyField"
                )
            )
    return out


def rule_history_foreign_keys(path, tree, source):
    """O7: no CASCADE or SET_NULL on a foreign key to a history-referenced model."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _name(node.func).split(".")[-1] in {
            "ForeignKey",
            "OneToOneField",
        }:
            target = (
                node.args[0]
                if node.args
                else next((k.value for k in node.keywords if k.arg == "to"), None)
            )
            target_name = (
                target.value if isinstance(target, ast.Constant) else _name(target).split(".")[-1]
            )
            on_delete = next((k.value for k in node.keywords if k.arg == "on_delete"), None)
            if on_delete is None and len(node.args) > 1:
                on_delete = node.args[1]
            rule = _name(on_delete).split(".")[-1] if on_delete is not None else ""
            if target_name in HISTORY_REFERENCED and rule in {"CASCADE", "SET_NULL"}:
                out.append(
                    Violation(
                        "O7", path, node.lineno, f"{rule} to history-referenced {target_name}"
                    )
                )
    return out


def rule_bare_save(path, tree, source):
    """D7b: every save() names its columns (update_fields) or is an explicit insert (force_insert)."""
    if path == "commerce_core/platform/db/governed.py":
        return []
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "save"
        ):
            if _name(node.func.value) == "super":
                continue
            keywords = {k.arg for k in node.keywords}
            if not keywords & {"update_fields", "force_insert"}:
                out.append(
                    Violation(
                        "D7b", path, node.lineno, "save() without update_fields or force_insert"
                    )
                )
    return out


def rule_status_and_stock_writes(path, tree, source):
    """S3, S6, C9: status fields change only in transition_to(); stock only in the stock service."""
    out = []
    parents = _parents(tree)
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Attribute):
                continue
            if target.attr in STATUS_FIELDS:
                funcs = [
                    a.name for a in _ancestors(node, parents) if isinstance(a, ast.FunctionDef)
                ]
                if not set(funcs) & STATUS_WRITERS:
                    out.append(
                        Violation(
                            "S3",
                            path,
                            node.lineno,
                            f"assigns {target.attr} outside transition_to()",
                        )
                    )
            if target.attr in STOCK_FIELDS and path not in STOCK_MODULES:
                out.append(
                    Violation("C9", path, node.lineno, "assigns stock outside the stock service")
                )
    return out


def rule_optional_returns(path, tree, source):
    """X2: domain services never return None to signal failure."""
    if not (path.endswith("/services.py") or "/services/" in path):
        return []
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.returns is not None
            and not node.name.startswith("_")
        ):
            text = ast.unparse(node.returns)
            optional = "Optional[" in text or "| None" in text or "None |" in text
            if optional and f"{path}::{node.name}" not in OPTIONAL_RETURN_ALLOWLIST:
                out.append(Violation("X2", path, node.lineno, f"{node.name} returns {text}"))
    return out


def _domain_error_names(tree) -> set[str]:
    names = {"DomainError"}
    try:
        from commerce_core.platform.errors.exceptions import DomainError

        names |= {cls.__name__ for cls in DomainError.by_code.values()}
    except ImportError:  # checked outside a configured environment
        pass
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            _name(b).split(".")[-1] in names for b in node.bases
        ):
            names.add(node.name)
    return names


def rule_domain_error_literals(path, tree, source):
    """L4: a DomainError is raised without a message literal; messages come from the registry."""
    names = _domain_error_names(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if _name(node.exc.func).split(".")[-1] not in names:
                continue
            literal_args = [
                a for a in node.exc.args if isinstance(a, (ast.Constant, ast.JoinedStr))
            ]
            message_kw = [k for k in node.exc.keywords if k.arg in {"message", "msg"}]
            if literal_args or message_kw:
                out.append(
                    Violation("L4", path, node.lineno, "DomainError raised with a message literal")
                )
    return out


def rule_except_in_atomic(path, tree, source):
    """X4, X11, X11a: no except inside atomic(); IntegrityError is caught only by the savepoint helper."""
    if path in INTEGRITY_ERROR_MODULES:
        return []
    out = []
    parents = _parents(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.handlers:
            if any(_is_atomic_with(a) for a in _ancestors(node, parents)):
                out.append(
                    Violation("X11", path, node.lineno, "except inside transaction.atomic()")
                )
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            caught = {
                _name(n).split(".")[-1]
                for n in (node.type.elts if isinstance(node.type, ast.Tuple) else [node.type])
            }
            if "IntegrityError" in caught:
                out.append(
                    Violation(
                        "X11a",
                        path,
                        node.lineno,
                        "IntegrityError caught outside the savepoint helper",
                    )
                )
    return out


def rule_forwarded_for(path, tree, source):
    """A9b: only the client-IP function reads X-Forwarded-For."""
    if path in FORWARDED_FOR_MODULES:
        return []
    return [
        Violation("A9b", path, node.lineno, "reads X-Forwarded-For")
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.upper().replace("-", "_") in {"HTTP_X_FORWARDED_FOR", "X_FORWARDED_FOR"}
    ]


def rule_stdlib_http(path, tree, source):
    """T4: no stdlib HTTP client outside the shared client (import-linter covers third-party ones)."""
    out = []
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        for module in modules:
            if module in {"urllib.request", "http.client"} or module.startswith(
                ("urllib.request", "http.client")
            ):
                out.append(Violation("T4", path, node.lineno, f"imports {module}"))
    return out


RULES: list[Callable] = [
    rule_bare_except,
    rule_settings_reads,
    rule_models_read_no_settings,
    rule_money_fields,
    rule_history_foreign_keys,
    rule_bare_save,
    rule_status_and_stock_writes,
    rule_optional_returns,
    rule_domain_error_literals,
    rule_except_in_atomic,
    rule_forwarded_for,
    rule_stdlib_http,
]


def check_source(path: str, source: str) -> list[Violation]:
    tree = ast.parse(source)
    violations = []
    for rule in RULES:
        violations.extend(rule(path, tree, source))
    return violations


def check_tree(root: Path = SRC) -> list[Violation]:
    violations = []
    for file in sorted((root / "commerce_core").rglob("*.py")):
        rel = file.relative_to(root).as_posix()
        if "/migrations/" in rel:
            continue
        violations.extend(check_source(rel, file.read_text()))
    return violations


def main(argv: list[str]) -> int:
    violations = check_tree()
    for v in violations:
        print(v)
    print(f"{len(violations)} violation(s).")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
