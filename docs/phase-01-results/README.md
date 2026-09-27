# Phase 1 verification results

Run on 2026-09-27 against core commit `9d9cfe3` (template `3e1e519`), PostgreSQL 16.13,
Python 3.12.14. No code was changed during the run.

| File | What it holds | Outcome |
|---|---|---|
| `bootstrap-release.txt` | fresh database → `bootstrap_db` (owner URL on stdin) → `manage.py release` twice, then ownership, grants, timeouts, seeds | every step exit=0; second release applies nothing |
| `pytest.txt` | `pytest -v -rA --durations=20`, test DB built by the migration role, tests as `commerce_web`/`commerce_job` | 390 passed, 0 skipped, 0 failed; exit=0 |
| `gates.txt` | every W8 gate with its exit code | all exit=0 after one rerun (below) |
| `test-map.md` | section 6 items and invariant-table rows → test ids / gates → result; N/A list; skipped list | 0 failing rows; 1 partial (D5 gap); DoD items pending on deployment and owner review |
| `mutmut.txt` | mutmut 3.8.0 on `platform` and `accounts`: summary, per module, every survivor with its diff | 3673 mutants: 1974 killed, 1323 survived, 185 no tests, 189 killed by signal, 2 timeouts; score 59.9% |

## Failures and irregularities recorded (not fixed)

1. **gates.txt, hash-install gate, first attempt exit=127.** The verification command left the
   interpreter path unquoted; the path contains a space. pip never ran. The same gate, quoted,
   exit=0; both are in the file.
2. **CI, `clean-install` job failed** on run 36337429134: the `commerce-deployment-template`
   repository and the two deploy-key secrets do not exist yet. Every other CI job passed or was
   skipped by design (`migration-review`: PRs only; `release-gates`: tags only; `upgrade-path`:
   disabled until 0.2.0).
3. **D5 gap:** no test races two inserts on `JobSchedule.name`'s unique constraint. The
   scheduler's `SKIP LOCKED` claim is tested; the constraint itself only by construction.
4. **mutmut, first attempt stopped in its stats phase**: the source-scanning AST test read
   mutmut's instrumented files. The rerun deselects the five tests that read source files.
5. **mutmut survivors: 1323.** Some reflect real gaps (for example `rate_limit.store.enforce`
   ignoring its principal survives), others reflect mutmut's attribution limits: code run at
   session setup, in threads, or in the worker subprocess. `conf/django_settings.build` runs
   once, at settings import, so all 283 of its mutants survive. Not triaged mutant by mutant.
6. **Definition of done items still open:** the owner's D1 read of the migrations, the owner's
   review of the build-time assumptions, deployment, and the two external monitors.
