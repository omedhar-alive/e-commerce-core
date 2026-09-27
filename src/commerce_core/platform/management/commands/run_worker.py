"""``manage.py run_worker``: the background task worker. Job role."""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the database-backed task worker (django-tasks-db)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch", action="store_true", help="Run outstanding tasks, then exit."
        )

    def handle(self, *args, batch, **options):
        call_command(
            "db_worker", "--queue-name", "*", "--no-reload", *(["--batch"] if batch else [])
        )
