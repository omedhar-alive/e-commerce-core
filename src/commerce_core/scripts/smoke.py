"""The deploy smoke script (phase 1 section 7, DoD "Deployed and verified").

    MONITORING_TOKEN=... commerce-smoke --base-url https://api.example.com --expect-version 0.1.0

Checks: ``/health`` 200, ``/health/jobs`` 200, ``/health/detail`` with the
monitoring token reports the expected version, the admin login page responds
and asks for a second factor, and a login without one is refused. The token
is read from the environment, never from the command line.
"""

import argparse
import os
import re
import sys

from commerce_core.platform.http import HttpClient


def run(
    base_url: str, token: str, expect_version: str | None, client: HttpClient | None = None
) -> list[tuple[str, bool, str]]:
    base = base_url.rstrip("/")
    client = client or HttpClient(follow_redirects=False)
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    r = client.get(f"{base}/health")
    check("/health is 200", r.status_code == 200, str(r.status_code))
    r = client.get(f"{base}/health/jobs")
    check("/health/jobs is 200", r.status_code == 200, str(r.status_code))
    r = client.get(f"{base}/health/detail", headers={"Authorization": f"Bearer {token}"})
    version = r.json().get("version") if r.status_code == 200 else None
    check(
        "/health/detail reports the core version",
        r.status_code == 200 and (expect_version is None or version == expect_version),
        f"{r.status_code} version={version}",
    )
    r = client.get(f"{base}/health/detail")
    check(
        "/health/detail refuses an unauthenticated request",
        r.status_code == 401,
        str(r.status_code),
    )

    login = client.get(f"{base}/admin/login/")
    check("admin login page responds", login.status_code == 200, str(login.status_code))
    check("admin login asks for a second factor", 'name="otp_token"' in login.text)
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login.text)
    csrf = match.group(1) if match else ""
    r = client.post(
        f"{base}/admin/login/",
        data={
            "csrfmiddlewaretoken": csrf,
            "username": "smoke@invalid.test",
            "password": "not-a-password",
        },
        headers={"Referer": f"{base}/admin/login/"},
    )
    check(
        "admin refuses a login without a second factor",
        r.status_code == 200 and "sessionid" not in r.cookies,
        str(r.status_code),
    )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expect-version", default=None)
    parser.add_argument(
        "--token-env", default="MONITORING_TOKEN", help="Environment variable holding the token."
    )
    args = parser.parse_args(argv)
    token = os.environ.get(args.token_env, "")
    if not token:
        print(f"{args.token_env} is not set.")
        return 2
    results = run(args.base_url, token, args.expect_version)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail and not ok else ''}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
