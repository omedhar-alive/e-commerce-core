"""X8: error codes are public API.

    python -m tools.checks.registry_diff PREVIOUS_TAG

Fails when a code present at the previous tag was removed or changed status,
unless the new version bumps the major number. Adding codes is fine.
"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = "src/commerce_core/platform/errors/registry.py"


def codes_from_source(source: str) -> dict[str, int]:
    codes = {}
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "ErrorSpec"
            and len(node.args) >= 2
        ):
            code, status = node.args[0], node.args[1]
            if isinstance(code, ast.Constant) and isinstance(status, ast.Constant):
                codes[code.value] = status.value
    return codes


def _major(version: str) -> int:
    return int(version.lstrip("v").split(".")[0])


def main(argv: list[str]) -> int:
    previous_tag = argv[0]
    before = codes_from_source(
        subprocess.run(
            ["git", "show", f"{previous_tag}:{REGISTRY}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    after = codes_from_source((ROOT / REGISTRY).read_text())
    removed = sorted(set(before) - set(after))
    changed = sorted(c for c in set(before) & set(after) if before[c] != after[c])
    from importlib.metadata import version

    if (removed or changed) and _major(version("commerce-core")) <= _major(previous_tag):
        for code in removed:
            print(f"X8: error code {code!r} removed since {previous_tag}")
        for code in changed:
            print(f"X8: error code {code!r} changed status {before[code]} -> {after[code]}")
        return 1
    print(f"X8: {len(after)} codes; none removed or changed since {previous_tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
