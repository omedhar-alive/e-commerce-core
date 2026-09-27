"""Which database role this process connects as (D6; decision 23).

Entry points declare their role explicitly: the WSGI entry point is web. A
``manage.py`` command's role comes from ``COMMAND_ROLE``; any other command
gets no database at all, so ``manage.py migrate`` cannot run outside the
release step (D2g).
"""

import sys
from pathlib import Path

from commerce_core.platform.conf.registry import Role

COMMAND_ROLE: dict[str, Role] = {
    "release": Role.MIGRATION,
    "create_staff": Role.WEB,
    "seed_demo": Role.JOB,
    "run_worker": Role.JOB,
    "run_scheduler": Role.JOB,
}

_UNSET = object()
_explicit = _UNSET


def set_role(role: Role | None) -> None:
    global _explicit
    _explicit = role


def detect_role(argv: list[str] | None = None) -> Role | None:
    if _explicit is not _UNSET:
        return _explicit
    argv = sys.argv if argv is None else argv
    if len(argv) >= 2 and Path(argv[0]).name in {"manage.py", "django-admin"}:
        return COMMAND_ROLE.get(argv[1])
    return None
