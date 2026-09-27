#!/usr/bin/env bash
# W8 clean-install test (W1, W1a, W1b, W2, W3): install core into a blank
# deployment skeleton, bootstrap a fresh database, run the release step, boot
# with default settings and pass the smoke script.
#
#   TEMPLATE_DIR=../commerce-deployment-template \
#   OWNER_URL=postgresql:///postgres \
#   CORE_SPEC=dist/commerce_core-0.1.0-py3-none-any.whl \
#   tools/clean_install.sh
#
# CORE_SPEC may be a wheel path or a git+ssh URL pinned to a tag or commit.
set -euo pipefail

: "${TEMPLATE_DIR:?}" "${OWNER_URL:?}" "${CORE_SPEC:?}"
PYTHON="${PYTHON:-python3.12}"
DB_NAME="${DB_NAME:-commerce_clean_install}"
PORT="${PORT:-8765}"
WORK="$(mktemp -d)"
trap 'kill "${GUNICORN_PID:-0}" 2>/dev/null || true; rm -rf "$WORK"' EXIT

echo "== W2: the template holds no models, migrations or domain code"
offenders=$(find "$TEMPLATE_DIR" -path "$TEMPLATE_DIR/.git" -prune -o \( -name models.py -o -name migrations -o -name services.py -o -name admin.py \) -print)
if [ -n "$offenders" ]; then echo "$offenders"; exit 1; fi

echo "== install core into a blank environment"
"$PYTHON" -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet --upgrade pip
"$WORK/venv/bin/pip" install --quiet "$CORE_SPEC" gunicorn==26.2.0 honcho==2.0.0
cp -R "$TEMPLATE_DIR/." "$WORK/app"
rm -rf "$WORK/app/.git"
cd "$WORK/app"

echo "== fresh database, bootstrapped by its owner"
DB_HOST_URL="${OWNER_URL%/*}"
psql "$OWNER_URL" -q -c "DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE)" -c "CREATE DATABASE $DB_NAME"
export DEPLOYMENT_ENV=local
export SECRET_KEY="clean-install-$(openssl rand -hex 32)"
export ALLOWED_HOSTS=127.0.0.1,localhost
export STORE_CURRENCY=EGP STORE_TIMEZONE=Africa/Cairo
export ALERT_RECIPIENTS=owner@example.test EMAIL_FROM=store@example.test SMTP_HOST=127.0.0.1
export MONITORING_TOKEN="$(openssl rand -hex 24)"
BOOT_OUT=$(echo "$DB_HOST_URL/$DB_NAME" | "$WORK/venv/bin/python" manage.py bootstrap_db)
echo "$BOOT_OUT" | grep -v ": " || true
role_url() {
  local role=$1 password
  password=$(echo "$BOOT_OUT" | awk -v r="  $role:" 'index($0, r) == 1 {print $2}')
  password=${password:-${ROLE_PASSWORD:-}}
  "$WORK/venv/bin/python" - "$DB_HOST_URL" "$role" "$password" "$DB_NAME" <<'PY'
import sys
from urllib.parse import quote, urlsplit
base, role, password, db = sys.argv[1:]
parts = urlsplit(base + "/x")
host = parts.hostname or ""
port = f":{parts.port}" if parts.port else ""
auth = f"{role}:{quote(password, safe='')}@" if password else f"{role}@"
print(f"postgresql://{auth}{host}{port}/{db}")
PY
}
export WEB_DATABASE_URL=$(role_url commerce_web)
export JOB_DATABASE_URL=$(role_url commerce_job)
export MIGRATION_DATABASE_URL=$(role_url commerce_migration)

echo "== release step as the migration role"
"$WORK/venv/bin/python" manage.py release

echo "== boot web with default settings"
"$WORK/venv/bin/gunicorn" deployment.wsgi --workers 1 --bind "127.0.0.1:$PORT" --daemon --pid "$WORK/gunicorn.pid" --error-logfile "$WORK/gunicorn.log"
for _ in $(seq 1 30); do
  curl -fs "http://127.0.0.1:$PORT/health" >/dev/null && break
  sleep 1
done
GUNICORN_PID=$(cat "$WORK/gunicorn.pid")
status=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/admin/login/")
echo "admin login page: $status"
[ "$status" = "200" ] || { cat "$WORK/gunicorn.log"; exit 1; }

echo "== smoke"
VERSION=$("$WORK/venv/bin/python" -c "from importlib.metadata import version; print(version('commerce-core'))")
"$WORK/venv/bin/commerce-smoke" --base-url "http://127.0.0.1:$PORT" --expect-version "$VERSION"

psql "$OWNER_URL" -q -c "DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE)"
echo "== clean install passed (core $VERSION)"
