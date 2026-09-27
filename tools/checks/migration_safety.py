"""CI gate for D2, D2b, D2c and D3 over core's migrations.

    python -m tools.checks.migration_safety [--previous-tag vX.Y.Z]

Migrations present at the previous release tag are "released"; the tables
they create are the existing tables D2b protects. Every core migration added
since is classified. Blocking, unsafe and RunPython findings fail the build;
destructive ones are listed for D3 (the release step then needs
``--restore-point``). With no previous tag (the first release) nothing
existed before, so only unsafe and RunPython findings can fail.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def released_migration_keys(tag: str | None) -> set[tuple[str, str]]:
    if not tag:
        return set()
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", tag, "--", "src/commerce_core"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    keys = set()
    for path in listing:
        parts = Path(path).parts
        if (
            len(parts) >= 4
            and parts[-2] == "migrations"
            and parts[-1].endswith(".py")
            and parts[-1][:4].isdigit()
        ):
            keys.add((parts[-3], parts[-1][:-3]))
    return keys


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-tag", default=None)
    args = parser.parse_args(argv)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tools.ci_settings")
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()
    from django.apps import apps
    from django.db.migrations.loader import MigrationLoader

    from commerce_core.platform.release.safety import classify, tables_created_by

    loader = MigrationLoader(None, ignore_no_migrations=True)
    core = {c.label for c in apps.get_app_configs() if c.name.startswith("commerce_core.")}
    released = released_migration_keys(args.previous_tag) & set(loader.graph.nodes)
    ordered = [k for k in loader.graph.leaf_nodes() for k in loader.graph.forwards_plan(k)]
    seen, plan = set(), []
    for key in ordered:
        if key not in seen:
            seen.add(key)
            plan.append(key)
    new = [k for k in plan if k[0] in core and k not in released]
    existing = tables_created_by(loader, sorted(released))

    findings = classify(loader, new, existing)
    failing = [f for f in findings if f.kind in {"blocking", "unsafe", "runpython"}]
    for finding in findings:
        print(("FAIL " if finding in failing else "D3   ") + str(finding))
    print(f"{len(new)} new core migration(s) checked against {len(existing)} existing table(s).")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
