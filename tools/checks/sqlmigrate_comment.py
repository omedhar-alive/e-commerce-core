"""D1: render the SQL of every migration a PR changes, for the PR comment.

    python -m tools.checks.sqlmigrate_comment BASE_REF > comment.md

Prints nothing and exits 0 when no migration changed; exits 3 when at least
one did (the workflow then posts the comment and requires the D1 checkbox).
"""

import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def changed_migrations(base: str) -> list[tuple[str, str, str]]:
    names = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=AM",
            f"{base}...HEAD",
            "--",
            "src/commerce_core",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    out = []
    for name in names:
        path = Path(name)
        if path.parent.name == "migrations" and path.suffix == ".py" and path.name[:4].isdigit():
            out.append((name, path.parent.parent.name, path.stem))
    return out


def main(argv: list[str]) -> int:
    migrations = changed_migrations(argv[0])
    if not migrations:
        return 0
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tools.ci_settings")
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()
    from django.core.management import call_command

    print("### Migration SQL for review (D1)\n")
    print(
        "Read each migration, its SQL below, and any `RunPython`/`RunSQL`, then tick the D1 box.\n"
    )
    for path, app, name in migrations:
        buffer = StringIO()
        call_command("sqlmigrate", app, name, stdout=buffer)
        print(
            f"<details><summary><code>{path}</code></summary>\n\n```sql\n{buffer.getvalue()}```\n</details>\n"
        )
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
