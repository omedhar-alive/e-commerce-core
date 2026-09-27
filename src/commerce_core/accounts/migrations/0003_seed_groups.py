"""Seed the A6a permissions and the three default groups.

Groups are created only if missing and are deployment-owned afterwards: a
deployment may regroup, and this migration never re-asserts membership
(decision 20). A later change to the defaults ships as its own migration.

Data is frozen here, not imported, so the migration never depends on domain
code (D2d). Bounded seed rows only (D2c).
"""

from django.db import migrations

PERMISSIONS = {
    "collect_cash": "Collect COD cash and record offline refund payouts",
    "request_refund": "Request a refund of a staff-chosen amount",
    "approve_refund": "Approve a refund (second approval)",
    "approve_cancellation": "Approve a cancellation",
    "adjust_stock": "Adjust stock",
    "resolve_review": "Resolve a payment review case",
    "manage_returns": "Manage returns",
    "change_address": "Change a shipping address",
    "create_shipment": "Create a shipment",
    "record_delivery": "Record a courier outcome",
    "record_receipt": "Record goods received back",
    "view_payment_events": "View raw payment events",
    "manage_settings": "Change runtime settings",
}

GROUPS = {
    "support": [
        "approve_cancellation",
        "change_address",
        "manage_returns",
        "collect_cash",
        "record_delivery",
    ],
    "warehouse": [
        "adjust_stock",
        "manage_returns",
        "create_shipment",
        "record_delivery",
        "record_receipt",
    ],
    "finance": [
        "request_refund",
        "approve_refund",
        "approve_cancellation",
        "collect_cash",
        "resolve_review",
        "view_payment_events",
    ],
}


def seed(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")

    content_type, _ = ContentType.objects.get_or_create(
        app_label="accounts", model="corepermissions"
    )
    permissions = {}
    for codename, name in PERMISSIONS.items():
        permissions[codename], _ = Permission.objects.get_or_create(
            content_type=content_type, codename=codename, defaults={"name": name}
        )
    for group_name, codenames in GROUPS.items():
        group, created = Group.objects.get_or_create(name=group_name)
        if created:
            group.permissions.set([permissions[c] for c in codenames])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_corepermissions"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
