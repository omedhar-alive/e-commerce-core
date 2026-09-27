"""``manage.py bootstrap_db``: one-time role and privilege setup (D6, T4a).

Run once per database by its owner. The owner connection URL is read from
standard input, or prompted for without echo on a terminal. It is never taken
from the command line (it would land in shell history and process lists), the
environment or the settings registry.
"""

import getpass
import sys

from django.core.management.base import BaseCommand

from commerce_core.platform.db.bootstrap import bootstrap


def read_owner_url(stdin=None) -> str:
    stdin = stdin or sys.stdin
    if stdin.isatty():
        return getpass.getpass("Owner database URL: ").strip()
    return stdin.readline().strip()


class Command(BaseCommand):
    help = "Create the four database roles, their timeouts and default privileges."
    requires_system_checks = []

    def handle(self, *args, **options):
        owner_url = read_owner_url()
        if not owner_url:
            self.stderr.write("No owner URL given on standard input.")
            sys.exit(2)
        result = bootstrap(owner_url)
        if result.created:
            self.stdout.write("Roles created. Store these passwords now; they are not shown again:")
            for role, password in result.created.items():
                self.stdout.write(f"  {role}: {password}")
        else:
            self.stdout.write("All roles already existed; timeouts and privileges re-applied.")
