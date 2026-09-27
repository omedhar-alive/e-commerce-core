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


def wsgi_application():
    set_role(Role.WEB)
    from django.core.wsgi import get_wsgi_application

    return get_wsgi_application()
