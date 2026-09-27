"""Generate the buyer-facing config reference from the settings registry (F1).

python -m tools.checks.config_reference          # rewrite the file
python -m tools.checks.config_reference --check  # CI: fail if stale
"""

import sys
from datetime import timedelta
from pathlib import Path

from commerce_core.platform.conf.registry import SETTINGS, Setting

OUTPUT = Path(__file__).resolve().parents[2] / "reference" / "config-reference.md"


def _duration(value: timedelta) -> str:
    seconds = int(value.total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _show(value) -> str:
    if isinstance(value, timedelta):
        return _duration(value)
    if isinstance(value, tuple):
        return ", ".join(value) or "(empty)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None or value == "":
        return "(unset)"
    return str(value)


def _default(setting: Setting) -> str:
    if setting.required:
        return "**required**"
    if setting.secret and setting.default:
        return "(secret)"
    return f"`{_show(setting.default)}`"


def _range(setting: Setting) -> str:
    if setting.choices:
        return " \\| ".join(f"`{c}`" for c in setting.choices)
    if setting.minimum is None and setting.maximum is None:
        return ""
    return f"{_show(setting.minimum)} – {_show(setting.maximum)}"


def render() -> str:
    lines = [
        "# Configuration reference",
        "",
        "Generated from `commerce_core.platform.conf.registry` by",
        "`python -m tools.checks.config_reference`. Do not edit by hand (F1).",
        "",
        "| Setting | Type | Default | Range | Class | Secret | Read by | Description |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in SETTINGS:
        roles = ", ".join(sorted(s.roles)) if s.roles else "all"
        description = s.description
        if s.required and s.manual_step:
            description += f" *Manual step:* {s.manual_step}"
        lines.append(
            f"| `{s.name}` | {s.type_label} | {_default(s)} | {_range(s)} | "
            f"{s.change_class} | {'yes' if s.secret else ''} | {roles} | {description} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        if not OUTPUT.exists() or OUTPUT.read_text() != text:
            print(f"{OUTPUT} is stale. Run: python -m tools.checks.config_reference")
            return 1
        return 0
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
