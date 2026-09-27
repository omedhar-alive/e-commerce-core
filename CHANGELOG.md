# Changelog

All notable changes to `commerce-core`. Semantic versioning (W4). Every entry
says whether the release needs a migration or a manual step.

## 0.1.0 — unreleased

Phase 1, foundation.

- Migrations: yes (first release; `accounts`, `platform`).
- Manual steps: run `bootstrap_db` once as the database owner before the first
  `release`; create the owner's staff account with `create_staff`.
