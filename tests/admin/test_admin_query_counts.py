"""Q1, Q3: every admin list and change page has a constant query count at two sizes."""

from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_tasks_db.models import DBTaskResult

from commerce_core.accounts.models import User
from commerce_core.platform.alerts.services import raise_alert
from commerce_core.platform.models import (
    Alert,
    JobSchedule,
    ReleaseRecord,
    RuntimeSetting,
    SettingChange,
)
from tests.accounts.helpers import make_staff, otp_login

pytestmark = pytest.mark.django_db


def _users(n):
    for i in range(n):
        u = User.objects.create_user(f"u{i}-{timezone.now().timestamp()}@x.com", None)
        TOTPDevice.objects.create(user=u, name="d", confirmed=True)


def _groups(n):
    Group.objects.bulk_create([Group(name=f"g{i}-{timezone.now().timestamp()}") for i in range(n)])


def _setting_changes(n):
    SettingChange.objects.bulk_create(
        [
            SettingChange(
                kind="checkout_kill_switch",
                before=False,
                after=True,
                actor_type="staff",
                actor_id="1",
                reason="r",
            )
            for _ in range(n)
        ]
    )


def _alerts(n):
    for i in range(n):
        raise_alert("job_stale", "job", f"x{i}-{timezone.now().timestamp()}")


def _jobs(n):
    JobSchedule.objects.bulk_create(
        [
            JobSchedule(name=f"probe-{i}-{timezone.now().timestamp()}", next_run_at=timezone.now())
            for i in range(n)
        ]
    )


def _releases(n):
    ReleaseRecord.objects.bulk_create(
        [ReleaseRecord(core_version="0.1.0", deployment_env="test") for _ in range(n)]
    )


def _task_results(n):
    DBTaskResult.objects.bulk_create(
        [
            DBTaskResult(
                args_kwargs={"args": [], "kwargs": {}},
                task_path="commerce_core.platform.jobs.registry.run_registered_job",
                queue_name="default",
                backend_name="default",
                run_after=timezone.now() + timedelta(days=1),
            )
            for _ in range(n)
        ]
    )


def _runtime(n):
    pass  # a fixed, seeded set of rows


BUILDERS = {
    User: _users,
    Group: _groups,
    TOTPDevice: _users,
    SettingChange: _setting_changes,
    Alert: _alerts,
    RuntimeSetting: _runtime,
    DBTaskResult: _task_results,
    ReleaseRecord: _releases,
    JobSchedule: _jobs,
}


def test_every_registered_admin_has_a_builder():
    assert set(admin.site._registry) <= set(BUILDERS), set(admin.site._registry) - set(BUILDERS)


@pytest.fixture
def staff_client(client):
    user, device = make_staff("qc@x.com", is_superuser=True)
    otp_login(client, user, device)
    return client


def _count(client, url):
    client.get(url)  # warm per-process caches (content types, session) before measuring
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    assert response.status_code == 200, (url, response.status_code)
    return len(ctx.captured_queries)


@pytest.mark.parametrize(
    "model", sorted(BUILDERS, key=lambda m: m._meta.label), ids=lambda m: m._meta.label
)
def test_changelist_query_count_is_constant(staff_client, model):
    if model not in admin.site._registry:
        pytest.skip("not registered in this admin")
    url = f"/admin/{model._meta.app_label}/{model._meta.model_name}/"
    BUILDERS[model](3)
    small = _count(staff_client, url)
    BUILDERS[model](9)
    assert _count(staff_client, url) == small


@pytest.mark.parametrize(
    "model", sorted(BUILDERS, key=lambda m: m._meta.label), ids=lambda m: m._meta.label
)
def test_change_page_query_count_is_constant(staff_client, model):
    if model not in admin.site._registry:
        pytest.skip("not registered in this admin")
    BUILDERS[model](3)
    obj = model.objects.order_by("pk").first()
    url = f"/admin/{model._meta.app_label}/{model._meta.model_name}/{obj.pk}/change/"
    small = _count(staff_client, url)
    BUILDERS[model](9)
    assert _count(staff_client, url) == small
