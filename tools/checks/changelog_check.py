"""W4: a release tag must have its changelog entry, saying whether it needs a migration or manual step.

python -m tools.checks.changelog_check vX.Y.Z
"""

import re
import sys
from importlib.metadata import version
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


def main(argv: list[str]) -> int:
    tag = argv[0]
    number = tag.removeprefix("v")
    problems = []
    if version("commerce-core") != number:
        problems.append(f"package version {version('commerce-core')} does not match tag {tag}")
    text = CHANGELOG.read_text()
    match = re.search(
        rf"^## {re.escape(number)} — (\d{{4}}-\d{{2}}-\d{{2}})$(.*?)(?=^## |\Z)", text, re.M | re.S
    )
    if not match:
        problems.append(f"CHANGELOG.md has no dated '## {number} — YYYY-MM-DD' entry")
    else:
        body = match.group(2)
        for label in ("Migrations:", "Manual steps:"):
            if label not in body:
                problems.append(f"CHANGELOG entry for {number} does not state '{label}'")
    for p in problems:
        print(f"W4: {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
