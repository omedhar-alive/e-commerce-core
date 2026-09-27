"""N4, N5: alerts are durable rows, one open per (code, subject), notified at least once."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from commerce_core.platform.actors import Actor
from commerce_core.platform.alerts import jobs as alert_jobs
from commerce_core.platform.alerts.services import (
    UnknownAlertCode,
    acknowledge_alert,
    raise_alert,
    resolve_alert,
)
from commerce_core.platform.errors.exceptions import ValidationFailed
from commerce_core.platform.jobs.registry import JOBS
from commerce_core.platform.models import Alert, JobSchedule

pytestmark = pytest.mark.django_db


def test_alert_is_written_in_its_causes_transaction():
    with transaction.atomic():
        raise_alert("job_stale", "job", "x")
        assert Alert.objects.count() == 1
    assert Alert.objects.count() == 1


def test_rollback_of_the_cause_leaves_no_alert():
    with pytest.raises(RuntimeError), transaction.atomic():
        raise_alert("job_stale", "job", "x")
        raise RuntimeError("cause failed")
    assert not Alert.objects.exists()


def test_retry_updates_the_open_alert_instead_of_adding_one():
    first = raise_alert("job_stale", "job", "x", {"attempt": 1})
    second = raise_alert("job_stale", "job", "x", {"attempt": 2})
    assert first == second
    alert = Alert.objects.get()
    assert alert.raise_count == 2 and alert.context == {"attempt": 2}


def test_after_resolution_a_new_alert_opens():
    first = raise_alert("job_stale", "job", "x")
    resolve_alert(first, Actor.system("test"))
    second = raise_alert("job_stale", "job", "x")
    assert second != first
    assert Alert.objects.filter(status="resolved").count() == 1


def test_database_refuses_a_second_open_alert():
    raise_alert("job_stale", "job", "x")
    with pytest.raises(IntegrityError, match="alert_one_open_per_subject"), transaction.atomic():
        Alert.objects.create(
            code="job_stale", severity="critical", subject_type="job", subject_id="x"
        )


def test_unknown_code_is_refused():
    with pytest.raises(UnknownAlertCode):
        raise_alert("made_up", "job", "x")


def test_acknowledge_and_resolve_record_a_typed_actor(django_user_model):
    user = django_user_model.objects.create_user("s@x.com", "a-long-password-1", is_staff=True)
    alert_id = raise_alert("job_stale", "job", "x")
    alert = acknowledge_alert(alert_id, Actor.staff(user))
    assert (alert.status, alert.acknowledged_by_type, alert.acknowledged_by_id) == (
        "acknowledged",
        "staff",
        str(user.pk),
    )
    alert = resolve_alert(alert_id, Actor.system("job_staleness_check"))
    assert (alert.status, alert.resolved_by_type, alert.resolved_by_id) == (
        "resolved",
        "system",
        "job_staleness_check",
    )
    with pytest.raises(ValidationFailed):
        acknowledge_alert(alert_id, Actor.staff(user))


def test_subject_is_a_typed_pair_not_a_foreign_key():
    assert not any(f.is_relation for f in Alert._meta.concrete_fields)


@pytest.mark.django_db(transaction=True)
def test_notification_job_emails_open_unnotified_alerts_at_least_once(
    smtp_server, override_setting
):
    override_setting("SMTP_PORT", smtp_server.port)
    before = len(smtp_server.inbox.messages)
    raise_alert("job_stale", "job", "x")
    alert_jobs.notify_alerts()
    alert_jobs.notify_alerts()  # already notified: not sent again
    sent = smtp_server.inbox.messages[before:]
    assert len(sent) == 1
    recipients, subject, body = sent[0]
    assert recipients == ("alerts@example.test",)
    assert "job_stale" in subject and "job x" in body
    assert Alert.objects.get().notified_at is not None


@pytest.mark.django_db(transaction=True)
def test_failed_notification_is_retried_next_run(smtp_server, override_setting):
    from tests.smtp_server import free_port

    raise_alert("job_stale", "job", "y")
    override_setting("SMTP_PORT", free_port())
    override_setting("SMTP_TIMEOUT", timedelta(seconds=1))
    alert_jobs.notify_alerts()
    assert Alert.objects.get().notified_at is None
    override_setting("SMTP_PORT", smtp_server.port)
    alert_jobs.notify_alerts()
    assert Alert.objects.get().notified_at is not None


def test_stopped_job_raises_job_stale_and_recovery_resolves_it():
    name = "task_result_pruning"
    long_ago = timezone.now() - JOBS[name].max_staleness - timedelta(minutes=1)
    JobSchedule.objects.update(created_at=timezone.now(), last_succeeded_at=timezone.now())
    JobSchedule.objects.filter(name=name).update(created_at=long_ago, last_succeeded_at=long_ago)
    alert_jobs.check_job_staleness()
    alert = Alert.objects.get(code="job_stale")
    assert (alert.subject_type, alert.subject_id, alert.status) == ("job", name, "open")
    alert_jobs.check_job_staleness()
    assert Alert.objects.filter(code="job_stale").count() == 1
    JobSchedule.objects.filter(name=name).update(last_succeeded_at=timezone.now())
    alert_jobs.check_job_staleness()
    alert.refresh_from_db()
    assert alert.status == "resolved" and alert.resolved_by_type == "system"
