"""``manage.py run_scheduler``: the in-core scheduler process (N4a; decision 14). Job role."""

import signal
import time

from django.core.management.base import BaseCommand, CommandError

from commerce_core.platform.jobs.registry import missing_schedules
from commerce_core.platform.jobs.scheduler import tick


class Command(BaseCommand):
    help = "Enqueue due registered jobs, forever (or once with --once)."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=15.0)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, interval, once, **options):
        missing = missing_schedules()
        if missing:
            raise CommandError(
                f"Registered jobs without a JobSchedule row: {', '.join(missing)}. "
                "Run the release step, which creates them."
            )
        stopping = []
        signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
        while not stopping:
            tick()
            if once:
                return
            time.sleep(interval)
