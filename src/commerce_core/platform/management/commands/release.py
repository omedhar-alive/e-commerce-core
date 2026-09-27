"""``manage.py release``: the one release step per deploy (D2g). Migration role."""

from django.core.management.base import BaseCommand

from commerce_core.platform.release.run import run_release


class Command(BaseCommand):
    help = (
        "Migrate forwards as the migration role, with lock retries and the D3 restore-point gate."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--restore-point",
            default="",
            help="Identifier of the backup or restore point taken just before this release (D3).",
        )
        parser.add_argument(
            "app_label", nargs="?", help="Migrate one app to a target (development only)."
        )
        parser.add_argument("migration_name", nargs="?")

    def handle(self, *args, restore_point, app_label, migration_name, **options):
        target = (app_label, migration_name) if app_label and migration_name else None
        record = run_release(restore_point=restore_point, target=target, stdout=self.stdout)
        self.stdout.write(
            f"Release recorded: core {record.core_version} ({record.deployment_env})."
        )
