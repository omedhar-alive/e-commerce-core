"""X8 and W4 tooling."""

import textwrap

from tools.checks.changelog_check import main as changelog_main
from tools.checks.registry_diff import codes_from_source


def test_registry_codes_are_read_from_source():
    source = textwrap.dedent(
        """
        _SPECS = (
            ErrorSpec("not_found", 404, ErrorClass.NOT_FOUND, _("x")),
            ErrorSpec("rate_limited", 429, ErrorClass.RATE_LIMITED, _("y"), details_keys=frozenset()),
        )
        """
    )
    assert codes_from_source(source) == {"not_found": 404, "rate_limited": 429}


def test_current_registry_parses_to_the_live_table():
    from pathlib import Path

    from tools.checks.registry_diff import REGISTRY, ROOT

    from commerce_core.platform.errors.registry import ERRORS

    parsed = codes_from_source((ROOT / REGISTRY).read_text())
    assert parsed == {code: spec.status for code, spec in ERRORS.items()}
    assert Path(ROOT / REGISTRY).exists()


def test_changelog_check(tmp_path, monkeypatch, capsys):
    from tools.checks import changelog_check

    log = tmp_path / "CHANGELOG.md"
    monkeypatch.setattr(changelog_check, "CHANGELOG", log)
    log.write_text("## 0.1.0 — unreleased\n\n- Migrations: yes\n")
    assert changelog_main(["v0.1.0"]) == 1
    assert "no dated" in capsys.readouterr().out
    log.write_text("## 0.1.0 — 2026-09-27\n\n- Migrations: yes\n- Manual steps: none\n")
    assert changelog_main(["v0.1.0"]) == 0
    assert changelog_main(["v0.2.0"]) == 1
