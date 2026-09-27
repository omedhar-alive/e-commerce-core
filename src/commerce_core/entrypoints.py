"""Process entry points. Each declares its database role before settings load.

A deployment's ``wsgi.py`` is::

    from commerce_core.entrypoints import wsgi_application
    application = wsgi_application()

The worker, scheduler and release step are ``manage.py`` commands whose role
comes from ``COMMAND_ROLE``. No entry point runs ``migrate`` (D2g): that is
the release step's job alone.
"""

from commerce_core.platform.conf.process import set_role
from commerce_core.platform.conf.registry import Role


def run_startup_checks() -> None:
    """Fail boot on any serious system check: route guard, governed admins, jobs (Q3a, D7b, N4a)."""
    from django.core import checks
    from django.core.management.base import SystemCheckError

    serious = [m for m in checks.run_checks() if m.is_serious()]
    if serious:
        raise SystemCheckError("\n".join(str(m) for m in serious))


def wsgi_application():
    set_role(Role.WEB)
    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()
    run_startup_checks()
    return application
