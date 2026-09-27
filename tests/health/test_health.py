"""N3, N4, N4a, N6, W3: three health endpoints, each revealing only what it may."""

from datetime import timedelta
from importlib.metadata import version

import pytest
from django.db import OperationalError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from commerce_core.platform.alerts import jobs as alert_jobs
from commerce_core.platform.alerts.services import raise_alert
from commerce_core.platform.jobs.registry import JOBS
from commerce_core.platform.models import JobSchedule
from tests.accounts.helpers import make_staff, otp_login
from tests.settings import TEST_ENV

pytestmark = pytest.mark.django_db
TOKEN = TEST_ENV["MONITORING_TOKEN"]


@pytest.fixture(autouse=True)
def fresh_jobs():
    JobSchedule.objects.update(created_at=timezone.now(), last_succeeded_at=timezone.now())


def _bearer(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def test_health_is_200_with_an_empty_body(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.content == b""


def test_health_is_503_when_the_database_is_unreachable(client, monkeypatch):
    def broken():
        raise OperationalError("down")

    monkeypatch.setattr(connection, "cursor", broken)
    response = client.get("/health")
    assert response.status_code == 503 and response.content == b""


def test_health_jobs_is_200_with_an_empty_body(client):
    response = client.get("/health/jobs")
    assert response.status_code == 200 and response.content == b""


def test_stopped_job_alerts_and_health_jobs_503_while_health_stays_200(client):
    name = "rate_limit_window_pruning"
    long_ago = timezone.now() - JOBS[name].max_staleness - timedelta(minutes=1)
    JobSchedule.objects.filter(name=name).update(last_succeeded_at=long_ago, created_at=long_ago)

    jobs = client.get("/health/jobs")
    assert jobs.status_code == 503 and jobs.content == b""
    assert client.get("/health").status_code == 200

    alert_jobs.check_job_staleness()
    detail = client.get("/health/detail", **_bearer(TOKEN)).json()
    assert {"code": "job_stale", "subject_type": "job", "subject_id": name}.items() <= detail[
        "open_critical_alerts"
    ][0].items()


def test_detail_refuses_unauthenticated_requests(client):
    response = client.get("/health/detail")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_detail_with_token_reports_the_core_version(client):
    body = client.get("/health/detail", **_bearer(TOKEN)).json()
    assert body["version"] == version("commerce-core") == "0.1.0"
    assert {j["name"] for j in body["jobs"]} == set(JOBS)


def test_detail_with_a_verified_staff_session(client):
    user, device = make_staff()
    otp_login(client, user, device)
    assert client.get("/health/detail").status_code == 200


def test_detail_refuses_a_staff_session_without_second_factor(client):
    user, _ = make_staff()
    client.force_login(user)
    assert client.get("/health/detail").status_code == 401


@pytest.mark.parametrize("token", ["wrong-" + "x" * 34, "", TOKEN[:-1]])
def test_detail_refuses_a_wrong_token(client, token):
    assert client.get("/health/detail", **_bearer(token)).status_code == 401


def test_token_opens_nothing_else(client):
    response = client.get("/admin/", **_bearer(TOKEN))
    assert response.status_code == 302 and "/admin/login/" in response["Location"]


def test_previous_token_only_inside_its_window(client, override_setting):
    previous = "p" * 40
    override_setting("MONITORING_TOKEN_PREVIOUS", previous)
    override_setting("MONITORING_TOKEN_ROTATED_AT", timezone.now() - timedelta(hours=1))
    assert client.get("/health/detail", **_bearer(previous)).status_code == 200
    override_setting("MONITORING_TOKEN_ROTATED_AT", timezone.now() - timedelta(hours=25))
    assert client.get("/health/detail", **_bearer(previous)).status_code == 401
    assert client.get("/health/detail", **_bearer(TOKEN)).status_code == 200


@pytest.mark.parametrize("n", [3, 9])
def test_detail_query_count_is_constant(client, n):
    for i in range(n):
        raise_alert("job_stale", "job", f"probe-{i}")
    with CaptureQueriesContext(connection) as ctx:
        assert client.get("/health/detail", **_bearer(TOKEN)).status_code == 200
    assert len(ctx.captured_queries) == 3
