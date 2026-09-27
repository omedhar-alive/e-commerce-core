"""Route guard (Q3a): every operation declares an explicit response schema.

A route with no ``response=``, or one whose response is a bare ``dict``/
``Any`` rather than a schema, fails at startup. A response schema may not
expose a field named ``id`` or ``pk``: responses identify entities by public
identifiers only (O6, Q3a).
"""

import typing

from pydantic import BaseModel

FORBIDDEN_FIELD_NAMES = frozenset({"id", "pk"})


def _schema_types(annotation) -> list:
    origin = typing.get_origin(annotation)
    if origin is None:
        return [annotation]
    out = []
    for arg in typing.get_args(annotation):
        out.extend(_schema_types(arg))
    return out


def _problems_for(annotation, where: str) -> list[str]:
    problems = []
    for kind in _schema_types(annotation):
        if kind is type(None):
            continue
        if not (isinstance(kind, type) and issubclass(kind, BaseModel)):
            problems.append(f"{where}: response is {kind!r}, not a schema")
            continue
        exposed = FORBIDDEN_FIELD_NAMES & set(kind.model_fields)
        if exposed:
            problems.append(f"{where}: schema {kind.__name__} exposes {sorted(exposed)}")
        for sub in kind.model_fields.values():
            nested = [
                t
                for t in _schema_types(sub.annotation)
                if isinstance(t, type) and issubclass(t, BaseModel)
            ]
            for model in nested:
                problems.extend(_problems_for(model, f"{where} -> {kind.__name__}"))
    return problems


def check_api(api) -> list[str]:
    from ninja.constants import NOT_SET

    problems = []
    api._get_bound_routers()
    for prefix, router in api._routers:
        for path, view in router.path_operations.items():
            for operation in view.operations:
                where = f"{api.urls_namespace}:{'/'.join(operation.methods)} {prefix}{path}"
                for status, model in operation.response_models.items():
                    if model is NOT_SET:
                        problems.append(f"{where}: no explicit response schema")
                        continue
                    if model is None:
                        continue
                    annotation = model.model_fields["response"].annotation
                    problems.extend(_problems_for(annotation, f"{where} [{status}]"))
    return problems
