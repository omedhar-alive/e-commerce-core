# Phase 1 — test map

Every item in section 6 of `phase-01-foundation.md` and every row of its section 5 invariant table,
mapped to test ids and gates, with the result read from `pytest.txt` and `gates.txt` in this folder.
CI results are from https://github.com/omedhar-alive/e-commerce-core/actions/runs/36337429134 (commit `9d9cfe3`).

Result key: **PASS** — every mapped test PASSED and every mapped gate exited 0. **PARTIAL / PENDING** — part of the item
is outside what can run yet (reason given). **N/A** — see section E. A test id with *(n cases)* is parametrized; all n passed.

## A. Every phase (Definition of done)

| Item | Evidence | Result |
|---|---|---|
| Tests pass, including the rule tests for every rule in Contracts that apply | pytest.txt: 390 results, all PASSED | PASS |
| Every rule in Contracts that apply has at least one passing test or CI gate | Sections B and C below; T3, X3, W5a waived by name (decision 17) | PASS |
| Every new list, detail or admin page has its query-count test; every new list endpoint its page-cap test (Q1, Q2, Q3) | `tests/admin/test_admin_query_counts.py` (every registered admin, list and change page), `tests/api/test_pagination.py`, `tests/health/test_health.py::test_detail_query_count_is_constant` | — |
| M11 total invariant holds in every test touching an order | N/A: no orders exist (landing phase 5) | N/A |
| The failure path was tested, not only the happy path | Refusal, rollback and timeout tests throughout; see sections B–D | PASS |
| Migrations read by a human (D1) and applied cleanly to a fresh database | Applied cleanly to a fresh database: bootstrap-release.txt (exit=0, second run no-op). Human read by the owner: **not yet done** | PARTIAL |
| Migrations applied to a database at the previous minor; previous suite passes (D2, W5) | N/A: first release; enabled from 0.2.0 (decision 8) | N/A |
| Every W8 CI gate passes | Locally: every gate exit=0 (gates.txt). CI https://github.com/omedhar-alive/e-commerce-core/actions/runs/36337429134: all passed except clean-install (template repo and deploy keys missing) | PARTIAL |
| The phase's invariant table has no empty cell | Section D: every row mapped | PASS |
| Nothing outside the phase's stated scope was modified | No change outside Phase 1 scope; additions made inside it are listed in Assumptions | PASS |
| The phase's Assumptions list has been reviewed by the owner | Build-time assumptions (Assumptions below and in the build report) not yet reviewed | PENDING |
| Deployed and verified: smoke passes against the deployment; both external monitors green | Smoke passes against a local live server and the local clean install. Not deployed; monitors not configured | PENDING |

## B. Section 6 — rule tests

| Rules | Item | Test ids / gates | Result |
|---|---|---|---|
| M1a, Q3b | zero- and three-decimal currencies round-trip through the Money schema; every amount carries its exponent | `tests/api/test_money_schema.py::test_zero_and_three_decimal_currencies_round_trip` (4 cases)<br>`tests/api/test_money_schema.py::test_exponent_is_always_present`<br>`tests/platform/test_money.py::test_exponents_come_from_the_iso_table` (9 cases) | PASS |
| M1b | a money column rejects a negative value (test-only model) | `tests/platform/test_money.py::test_negative_amount_refused_by_db`<br>`tests/platform/test_money.py::test_money_column_is_bigint` | PASS |
| A1a | two emails differing only in case cannot create two accounts | `tests/accounts/test_email.py::test_case_variants_cannot_create_two_accounts`<br>`tests/accounts/test_email.py::test_database_refuses_raw_case_variant`<br>`tests/accounts/test_email.py::test_queryset_update_normalizes`<br>`tests/concurrency/test_d5.py::test_email_concurrent_insert_one_wins` | PASS |
| A1b | Argon2id hash stored; a password failing the validators is refused | `tests/accounts/test_passwords.py::test_stored_hash_is_argon2id`<br>`tests/accounts/test_passwords.py::test_validator_refuses_weak_password_and_keeps_old_one` | PASS |
| A6a | changing a runtime setting is refused without manage_settings | `tests/platform/test_runtime_settings.py::test_refused_without_manage_settings`<br>`tests/platform/test_runtime_settings.py::test_admin_change_view_refused_without_permission`<br>`tests/accounts/test_permissions.py::test_all_a6a_permissions_exist_in_the_database`<br>`tests/accounts/test_permissions.py::test_default_groups_match_the_handoff` | PASS |
| A6b | staff cannot reach the admin without a second factor; an idle session expires | `tests/accounts/test_admin_otp.py::test_staff_without_device_cannot_log_in`<br>`tests/accounts/test_admin_otp.py::test_password_session_without_second_factor_is_refused`<br>`tests/accounts/test_admin_otp.py::test_wrong_token_is_refused`<br>`tests/accounts/test_admin_otp.py::test_idle_session_expires` | PASS |
| A9, A9a | a limit holds at its boundary under concurrent requests on two connections | `tests/concurrency/test_d5.py::test_rate_limit_holds_at_boundary_under_concurrency`<br>`tests/platform/test_ratelimit.py::test_limit_holds_at_its_boundary` | PASS |
| A9b | a spoofed X-Forwarded-For does not change the recorded IP | `tests/platform/test_client_ip.py::test_spoofed_xff_does_not_change_the_ip`<br>`tests/platform/test_client_ip.py::test_no_trusted_hops_uses_remote_addr_and_ignores_xff` | PASS |
| A11 | a missing required secret fails boot | `tests/platform/test_settings_registry.py::test_missing_required_secret_fails_boot` | PASS |
| A12, X15, X13a | logs and error reports contain no secrets, tokens, email, phone, name or address | `tests/platform/test_redaction.py::test_free_text_secrets_are_scrubbed_from_messages` (7 cases)<br>`tests/platform/test_redaction.py::test_named_fields_are_replaced_whole`<br>`tests/platform/test_redaction.py::test_exception_text_is_scrubbed`<br>`tests/platform/test_redaction.py::test_sentry_event_is_scrubbed`<br>`tests/platform/test_redaction.py::test_request_log_through_the_api_contains_no_pii` | PASS |
| D2a | a migration that can't get its lock fails at 3 s and retries | `tests/release/test_release.py::test_real_migration_lock_fails_at_three_seconds_and_retries`<br>`tests/release/test_release.py::test_lock_timeout_retries_with_exponential_backoff`<br>`tests/release/test_release.py::test_lock_timeout_fails_the_deploy_after_the_last_retry` | PASS |
| D2b, D3 | CI rejects a blocking migration on an existing table and flags a destructive one; release refuses it without a restore point, production and non-production | `tests/static/test_migration_safety.py::test_rejects_plain_index_on_existing_table`<br>`tests/static/test_migration_safety.py::test_rejects_validated_check_constraint_on_existing_table`<br>`tests/static/test_migration_safety.py::test_flags_drop_column_and_table_as_destructive`<br>`tests/release/test_release.py::test_destructive_migration_refused_without_restore_point_in_every_environment` (4 cases)<br>`tests/release/test_release.py::test_release_step_refuses_before_migrating` (2 cases)<br>local gate *blocking-migration check (D2, D2b, D2c, D3)* (exit=0) | PASS |
| D2f | makemigrations --check passes; no model reads a setting | local gate *makemigrations --check (D2f)* (exit=0)<br>`tests/static/test_ast_rules.py::test_models_may_not_read_settings`<br>CI job `migrations`: success | PASS |
| D6 | web and job cannot run DDL; each role reports its T4a timeouts | `tests/db/test_roles.py::test_web_and_job_cannot_run_ddl` (10 cases)<br>`tests/db/test_roles.py::test_role_reports_its_timeouts` (4 cases)<br>`tests/db/test_roles.py::test_roles_are_not_privileged` (4 cases) | PASS |
| D7 | web and job cannot update or delete SettingChange | `tests/platform/test_runtime_settings.py::test_web_and_job_cannot_update_or_delete_setting_change` (4 cases)<br>`tests/db/test_grants.py::test_append_only_refuses_update_and_delete` (4 cases) | PASS |
| D7b | a bare save() on a governed test model is refused by the DB and by the static check; no admin change form can save one | `tests/db/test_grants.py::test_bare_save_is_refused_by_the_database_too`<br>`tests/db/test_grants.py::test_bare_save_is_refused_before_sql`<br>`tests/static/test_ast_rules.py::test_each_rule_catches_its_form` (13 cases)<br>`tests/platform/test_runtime_settings.py::test_governed_admin_check_passes_and_catches_a_writable_admin`<br>`tests/platform/test_runtime_settings.py::test_admin_forms_are_read_only_even_for_superusers` | PASS |
| D5 | the uniqueness rows here (email, alert, rate-limit window, job schedule) each have a concurrency test | `tests/concurrency/test_d5.py::test_email_concurrent_insert_one_wins`<br>`tests/concurrency/test_d5.py::test_alert_retry_on_two_connections_keeps_one_open_alert`<br>`tests/concurrency/test_d5.py::test_rate_limit_holds_at_boundary_under_concurrency`<br>`tests/concurrency/test_d5.py::test_two_schedulers_enqueue_each_run_once`<br>`tests/concurrency/test_d5.py::test_runtimesetting_unique_nulls_not_distinct`<br>`tests/concurrency/test_d5.py::test_business_day_marker_concurrent_insert_one_wins`<br>**Gap:** the job-schedule test proves `FOR UPDATE SKIP LOCKED` (one enqueue per run); no test races two inserts on `JobSchedule.name`'s unique constraint. | PARTIAL (gap noted) |
| X5a, X7, X10a | every returned code is registered with its status; every error body has request_id; an inbound X-Request-ID is logged as upstream_request_id or dropped | `tests/platform/test_errors.py::test_every_code_has_exactly_one_exception_class`<br>`tests/api/test_error_shape.py::test_domain_error_body`<br>`tests/api/test_error_shape.py::test_validation_error_names_each_field`<br>`tests/api/test_request_id.py::test_inbound_id_never_replaces_request_id`<br>`tests/api/test_request_id.py::test_valid_upstream_id_is_kept`<br>`tests/api/test_request_id.py::test_invalid_upstream_id_is_dropped` (5 cases)<br>`tests/platform/test_redaction.py::test_request_log_through_the_api_contains_no_pii` | PASS |
| X7, L3a | an error message renders in the request language and its code doesn't change | `tests/platform/test_locale.py::test_error_message_renders_in_request_language_and_code_does_not_change`<br>`tests/platform/test_locale.py::test_every_error_message_has_an_arabic_translation` | PASS |
| X11a | a named unique violation inside the savepoint is retried; any other constraint re-raises | `tests/platform/test_savepoint.py::test_named_violation_is_retried_with_a_new_value`<br>`tests/platform/test_savepoint.py::test_named_violation_is_treated_as_replay_and_outer_transaction_survives`<br>`tests/platform/test_savepoint.py::test_other_constraint_reraises` | PASS |
| X14 | production refuses to boot without ERROR_TRACKING_DSN | `tests/platform/test_settings_registry.py::test_production_requires_error_tracking_dsn` | PASS |
| F1a | a missing, mistyped or out-of-range setting fails boot | `tests/platform/test_settings_registry.py::test_missing_required_setting_fails_boot`<br>`tests/platform/test_settings_registry.py::test_mistyped_setting_fails_boot`<br>`tests/platform/test_settings_registry.py::test_out_of_range_setting_fails_boot` | PASS |
| F1c | only runtime settings change at runtime; each change writes an audit row | `tests/platform/test_settings_registry.py::test_runtime_settings_are_exactly_the_kill_switch_in_phase_1`<br>`tests/platform/test_settings_registry.py::test_get_setting_refuses_undeclared_runtime_and_unread`<br>`tests/platform/test_runtime_settings.py::test_change_writes_audit_row_with_typed_actor`<br>`tests/platform/test_runtime_settings.py::test_failure_rolls_back_both` | PASS |
| N3 | /health and /health/jobs reveal only their status code; /health/detail refuses unauthenticated requests; the token opens nothing else; the previous token works only inside its window | `tests/health/test_health.py::test_health_is_200_with_an_empty_body`<br>`tests/health/test_health.py::test_health_jobs_is_200_with_an_empty_body`<br>`tests/health/test_health.py::test_detail_refuses_unauthenticated_requests`<br>`tests/health/test_health.py::test_token_opens_nothing_else`<br>`tests/health/test_health.py::test_previous_token_only_inside_its_window` | PASS |
| N4, N4a, N6 | a stopped job alerts and /health/jobs returns 503 while /health stays 200 | `tests/health/test_health.py::test_stopped_job_alerts_and_health_jobs_503_while_health_stays_200`<br>`tests/platform/test_alerts.py::test_stopped_job_raises_job_stale_and_recovery_resolves_it`<br>`tests/release/test_smoke_and_seed.py::test_smoke_script_fails_on_a_stale_job` | PASS |
| N5 | an alert is written in its cause's transaction; a retry never opens a second open alert | `tests/platform/test_alerts.py::test_alert_is_written_in_its_causes_transaction`<br>`tests/platform/test_alerts.py::test_rollback_of_the_cause_leaves_no_alert`<br>`tests/platform/test_alerts.py::test_retry_updates_the_open_alert_instead_of_adding_one`<br>`tests/concurrency/test_d5.py::test_alert_retry_on_two_connections_keeps_one_open_alert` | PASS |
| Q2a, Q2b, Q3, Q3a, Q3c | paging while rows are inserted never repeats or skips a row | `tests/api/test_pagination.py::test_paging_while_rows_are_inserted_never_repeats_or_skips` (4 cases)<br>`tests/api/test_pagination.py::test_ties_on_the_sort_key_are_broken_by_public_id` | PASS |
| Q2a, Q2b, Q3, Q3a, Q3c | page size defaults to 20 and clamps at 100 | `tests/api/test_pagination.py::test_page_size_defaults_to_20_and_clamps_at_100` | PASS |
| Q2a, Q2b, Q3, Q3a, Q3c | no cursor decodes to a primary key | `tests/api/test_pagination.py::test_no_cursor_decodes_to_a_primary_key`<br>`tests/api/test_pagination.py::test_responses_carry_no_primary_key` | PASS |
| Q2a, Q2b, Q3, Q3a, Q3c | an unknown filter or sort returns 400 | `tests/api/test_pagination.py::test_unknown_filter_or_sort_is_400` (3 cases)<br>`tests/api/test_pagination.py::test_every_allowlisted_sort_and_filter_is_indexed` | PASS |
| Q2a, Q2b, Q3, Q3a, Q3c | query count is constant at two sizes | `tests/api/test_pagination.py::test_query_count_is_constant_at_two_sizes` (2 cases) | PASS |
| Q2a, Q2b, Q3, Q3a, Q3c | a body over 1 MB is refused | `tests/api/test_body_cap.py::test_body_over_cap_is_413`<br>`tests/api/test_body_cap.py::test_refused_before_parsing` | PASS |
| T1 | the shared client raises inside atomic() | `tests/platform/test_http.py::test_raises_inside_atomic_before_any_request` | PASS |
| T4a | a transaction blocked on a lock fails at lock_timeout with a retryable 503 | `tests/api/test_error_shape.py::test_lock_timeout_is_a_retryable_503`<br>`tests/db/test_timeouts.py::test_web_lock_wait_fails_at_lock_timeout` | PASS |
| L1, L1a | day boundaries and a business-day job are correct across a DST transition | `tests/platform/test_business_day.py::test_spring_forward_day_is_23_hours`<br>`tests/platform/test_business_day.py::test_fall_back_day_is_25_hours`<br>`tests/platform/test_business_day.py::test_business_day_job_runs_exactly_once_per_local_date_across_dst` (2 cases) | PASS |
| W1b, W8, W3 | the clean-install test boots the template with the admin login page responding; /health/detail reports the core version | local gate *clean-install test (W1, W1b, W2, W3, W8)* (exit=0)<br>`tests/health/test_health.py::test_detail_with_token_reports_the_core_version`<br>`tests/release/test_smoke_and_seed.py::test_smoke_script_passes_against_a_live_server`<br>CI job `clean-install`: failure (template repo and deploy keys not set up) | PASS (locally); CI pending |

## C. Section 6 — rules proven by a CI gate

| Rules | Item | Test ids / gates | Result |
|---|---|---|---|
| W8a: X1 | no bare except | local gate *ruff check* (exit=0)<br>local gate *AST checks (W8a)* (exit=0)<br>`tests/static/test_ast_rules.py::test_each_rule_catches_its_form` (13 cases)<br>CI job `lint`: success<br>CI job `static-checks`: success | PASS |
| W8a: X6 | domain imports no API layer | local gate *import-linter (T4, X6, D2d)* (exit=0)<br>CI job `static-checks`: success | PASS |
| W8a: T4, P17 | no HTTP or provider imports outside their layers | local gate *import-linter (T4, X6, D2d)* (exit=0)<br>local gate *AST checks (W8a)* (exit=0)<br>CI job `static-checks`: success<br>P17: no provider layer exists yet; the contract is added with payments (phase 6). | PASS |
| W8a: M1 | money field type | local gate *AST checks (W8a)* (exit=0)<br>`tests/static/test_ast_rules.py::test_money_rules`<br>CI job `static-checks`: success | PASS |
| W8a: O7 | no CASCADE or SET_NULL to history-referenced models (no targets yet) | local gate *AST checks (W8a)* (exit=0)<br>`tests/static/test_ast_rules.py::test_history_foreign_keys`<br>CI job `static-checks`: success | PASS |
| W8a: D7b, F1a | bare save; settings reads | local gate *AST checks (W8a)* (exit=0)<br>`tests/static/test_ast_rules.py::test_each_rule_catches_its_form` (13 cases)<br>`tests/static/test_ast_rules.py::test_core_passes_every_static_check`<br>CI job `static-checks`: success | PASS |
| W8a: S3, S6, C9 | assignment checks, wired with no target fields yet | local gate *AST checks (W8a)* (exit=0)<br>`tests/static/test_ast_rules.py::test_each_rule_catches_its_form` (13 cases)<br>`tests/static/test_ast_rules.py::test_allowed_forms_pass` (4 cases)<br>CI job `static-checks`: success | PASS |
| W1, W1a | CI installs by tag from the private repo with a deploy key | local gate *clean-install test (W1, W1b, W2, W3, W8)* (exit=0)<br>CI job `clean-install`: failure (template repo and deploy keys not set up)<br>Locally the built wheel was installed; the git+ssh/deploy-key path has only run in CI, where it failed before install (template repo missing). | PASS (locally); CI pending |
| W1b | admin ships inside core | local gate *clean-install test (W1, W1b, W2, W3, W8)* (exit=0)<br>`tests/accounts/test_admin_otp.py::test_admin_login_page_responds` | PASS |
| W2 | the template contains no models, migrations or domain code | local gate *clean-install test (W1, W1b, W2, W3, W8)* (exit=0) | PASS |
| W2a | notification channel port contract suite against the SMTP adapter with a local SMTP server | `tests/platform/test_notification_contract.py::TestSmtpAdapter::test_implements_the_port`<br>`tests/platform/test_notification_contract.py::TestSmtpAdapter::test_delivers_to_every_recipient_with_body_intact`<br>`tests/platform/test_notification_contract.py::TestSmtpAdapter::test_refuses_to_send_inside_a_transaction`<br>`tests/platform/test_notification_contract.py::TestSmtpAdapter::test_unreachable_server_is_a_transient_failure`<br>`tests/platform/test_notification_contract.py::TestSmtpAdapter::test_no_recipients_is_a_permanent_failure` | PASS |
| W4 | CI fails a tag with no changelog entry | `tests/static/test_release_tools.py::test_changelog_check`<br>CI job `release-gates`: skipped (runs on v* tags only; none pushed) | PASS (locally); CI pending |
| X8 | CI fails when a registry code is removed or its status changed against the previous tag | `tests/static/test_release_tools.py::test_registry_codes_are_read_from_source`<br>`tests/static/test_release_tools.py::test_current_registry_parses_to_the_live_table`<br>CI job `release-gates`: skipped (runs on v* tags only; none pushed)<br>No previous tag exists, so the diff itself has nothing to compare until 0.2.0. | PASS (locally); CI pending |
| W5, W6 | release refuses a deployment more than one minor behind | `tests/release/test_release.py::test_one_minor_version_at_a_time` (6 cases)<br>`tests/release/test_release.py::test_release_refuses_a_deployment_two_minors_behind` | PASS |
| D2d | import-linter forbids migrations from importing domain code | local gate *import-linter (T4, X6, D2d)* (exit=0)<br>CI job `static-checks`: success | PASS |
| D2g | no process entry point runs migrate | `tests/release/test_entrypoints.py::test_no_process_entry_point_runs_migrate`<br>`tests/release/test_entrypoints.py::test_detect_role_from_command` (6 cases) | PASS |
| D4a, M3a, F1e | BACKUP_RPO/RTO declared with defaults; STORE_CURRENCY validated against ISO; every setting has a default or a manual step | `tests/platform/test_settings_registry.py::test_backup_rpo_and_rto_declared_with_defaults`<br>`tests/platform/test_settings_registry.py::test_store_currency_validated_against_iso_table`<br>`tests/platform/test_settings_registry.py::test_unknown_store_currency_fails_boot`<br>`tests/platform/test_settings_registry.py::test_every_setting_has_default_or_manual_step` | PASS |
| A2, A5 | an admin POST without a CSRF token is refused | `tests/accounts/test_admin_csrf.py::test_login_post_without_csrf_token_is_refused`<br>`tests/accounts/test_admin_csrf.py::test_admin_change_post_without_csrf_token_is_refused`<br>`tests/accounts/test_admin_csrf.py::test_admin_uses_session_authentication` | PASS |
| X9, X10 | handler maps each registry class to its status; production boot refuses DEBUG=True | `tests/api/test_error_shape.py::test_class_status_map_per_x9`<br>`tests/platform/test_errors.py::test_every_status_matches_its_x9_class`<br>`tests/platform/test_settings_registry.py::test_production_refuses_debug`<br>`tests/api/test_error_shape.py::test_unhandled_becomes_internal_error_without_internals` | PASS |
| L4 | a static check forbids message literals in DomainError raises | local gate *AST checks (W8a)* (exit=0)<br>`tests/static/test_ast_rules.py::test_each_rule_catches_its_form` (13 cases) | PASS |
| A1 | AUTH_USER_MODEL is set and accounts.0001 is the first core migration (C4 wording) | `tests/accounts/test_migration_graph.py::test_auth_user_model_is_set`<br>`tests/accounts/test_migration_graph.py::test_accounts_0001_depends_only_on_contrib`<br>`tests/accounts/test_migration_graph.py::test_accounts_0001_is_first_core_migration_and_every_other_descends_from_it` | PASS |
| F1, F2 | config reference regenerated from the registry and not stale; F2 via the W2 template check | local gate *config reference is current (F1)* (exit=0)<br>local gate *clean-install test (W1, W1b, W2, W3, W8)* (exit=0)<br>CI job `config-reference`: success | PASS |
| S4 | a SettingChange row records a typed actor | `tests/platform/test_runtime_settings.py::test_change_writes_audit_row_with_typed_actor`<br>`tests/platform/test_runtime_settings.py::test_actor_type_is_a_closed_set_in_the_db`<br>`tests/platform/test_alerts.py::test_acknowledge_and_resolve_record_a_typed_actor` | PASS |
| X5 | covered by X5a's import-time check | `tests/platform/test_errors.py::test_unregistered_code_fails_at_import`<br>`tests/platform/test_errors.py::test_second_class_for_a_code_fails_at_import` | PASS |
| X13 | error logs carry request_id | `tests/platform/test_redaction.py::test_error_logs_carry_request_id_and_upstream`<br>`tests/platform/test_redaction.py::test_request_log_through_the_api_contains_no_pii` | PASS |
| X4, X11 | no except inside atomic() except the X11a helper | local gate *AST checks (W8a)* (exit=0)<br>`tests/static/test_ast_rules.py::test_each_rule_catches_its_form` (13 cases) | PASS |
| D2c | RunPython only in allowlisted seed migrations | local gate *blocking-migration check (D2, D2b, D2c, D3)* (exit=0)<br>`tests/static/test_migration_safety.py::test_runpython_outside_allowlist_is_rejected`<br>`tests/static/test_migration_safety.py::test_every_shipped_core_migration_passes` | PASS |
| D1 | CI posts sqlmigrate of changed migrations and fails the PR unless the box is ticked | CI job `migration-review`: skipped (runs on pull requests only; none opened)<br>Tool renders SQL (verified by hand against local Postgres during the build). The job has never run: no pull request has been opened. The human read of 0.1.0's migrations by the owner is still outstanding. | PENDING |
| D2h | release refuses any target that would unapply a migration in production | `tests/release/test_release.py::test_production_refuses_a_backwards_plan` | PASS |
| X2 | static check refuses Optional/None returns in domain services outside the allowlist | local gate *AST checks (W8a)* (exit=0)<br>`tests/static/test_ast_rules.py::test_optional_returns_in_services` | PASS |
| Lockfile, pip-audit (W8) | hash-pinned lockfile; pip-audit | local gate *lockfile: uv lock --check* (exit=0)<br>local gate *lockfile: export matches requirements.lock* (exit=0)<br>local gate *lockfile: install with --require-hashes* (exit=0)<br>local gate *pip-audit* (exit=0)<br>CI job `lockfile`: success | PASS |
| Ruff format (W8a) | formatting | local gate *ruff format --check* (exit=0)<br>CI job `lint`: success | PASS |
| L3 (translations) | compiled catalogues current | local gate *compiled translations are current (L3)* (exit=0)<br>CI job `static-checks`: success | PASS |

### Waived by name

| Rule | Reason |
|---|---|
| T3 | waived (decision 17): small atomic() blocks, proven by review; backstopped by T4a timeouts and the T1 guard |
| X3 | waived (decision 17): except recovers or re-raises, proven by review; X1's static check covers the worst forms |
| W5a | waived (decision 17): commercial term for the license (W9); no code path |

## D. Section 5 — invariant table

| Invariant | Test ids / gates | Result |
|---|---|---|
| One account per email, case-insensitively (A1a) | `tests/accounts/test_email.py::test_case_variants_cannot_create_two_accounts`<br>`tests/accounts/test_email.py::test_database_refuses_raw_case_variant`<br>`tests/accounts/test_email.py::test_queryset_update_normalizes`<br>`tests/concurrency/test_d5.py::test_email_concurrent_insert_one_wins` | PASS |
| One phone format (E.164) | `tests/accounts/test_phone.py::test_normalizes_to_e164` (2 cases)<br>`tests/accounts/test_phone.py::test_invalid_phone_raises_validation_error` (3 cases)<br>`tests/accounts/test_phone.py::test_field_normalizes_on_save_and_update`<br>`tests/accounts/test_phone.py::test_invalid_phone_on_write_raises_validation_error` | PASS |
| Password hashed with Argon2id (A1b) | `tests/accounts/test_passwords.py::test_stored_hash_is_argon2id`<br>`tests/accounts/test_passwords.py::test_validator_refuses_weak_password_and_keeps_old_one` | PASS |
| Credentials die with deactivation or password change (A4b) | `tests/accounts/test_token_version.py::test_deactivation_bumps`<br>`tests/accounts/test_token_version.py::test_password_change_bumps`<br>`tests/accounts/test_token_version.py::test_admin_deactivation_bumps`<br>`tests/accounts/test_token_version.py::test_bump_is_a_single_atomic_increment` | PASS |
| Staff reach the admin only with TOTP (A6b) | `tests/accounts/test_admin_otp.py::test_staff_without_device_cannot_log_in`<br>`tests/accounts/test_admin_otp.py::test_password_session_without_second_factor_is_refused`<br>`tests/accounts/test_admin_otp.py::test_idle_session_expires`<br>`tests/accounts/test_create_staff.py::test_creates_staff_with_confirmed_device_and_prints_uri` | PASS |
| Privileged actions check a named permission (A6a) | `tests/accounts/test_permissions.py::test_all_a6a_permissions_exist_in_the_database`<br>`tests/accounts/test_permissions.py::test_require_refuses_without_the_named_permission`<br>`tests/accounts/test_permissions.py::test_seed_never_overwrites_a_regrouped_deployment`<br>`tests/platform/test_runtime_settings.py::test_refused_without_manage_settings` | PASS |
| Every setting is valid at boot (F1a, A11) | `tests/platform/test_settings_registry.py::test_missing_required_secret_fails_boot`<br>`tests/platform/test_settings_registry.py::test_mistyped_setting_fails_boot`<br>`tests/release/test_entrypoints.py::test_each_process_reads_only_its_role_url` (3 cases)<br>local gate *AST checks (W8a)* (exit=0) | PASS |
| Runtime settings are exactly the kill switch and provider toggles, audited (F1c; decision 22) | `tests/platform/test_runtime_settings.py::test_unknown_kind_refused_by_db`<br>`tests/platform/test_runtime_settings.py::test_kill_switch_with_provider_key_refused_by_db`<br>`tests/platform/test_runtime_settings.py::test_second_kill_switch_row_refused_by_db`<br>`tests/platform/test_runtime_settings.py::test_change_writes_audit_row_with_typed_actor`<br>`tests/platform/test_runtime_settings.py::test_failure_rolls_back_both`<br>`tests/concurrency/test_d5.py::test_runtimesetting_unique_nulls_not_distinct` | PASS |
| SettingChange is append-only (D7) | `tests/platform/test_runtime_settings.py::test_web_and_job_cannot_update_or_delete_setting_change` (4 cases)<br>`tests/db/test_grants.py::test_declared_governance_matches_database_grants` | PASS |
| Governed writes name their columns (D7b) | `tests/db/test_grants.py::test_bare_save_is_refused_by_the_database_too`<br>`tests/db/test_grants.py::test_bare_save_is_refused_before_sql`<br>`tests/platform/test_runtime_settings.py::test_governed_admin_check_passes_and_catches_a_writable_admin`<br>local gate *AST checks (W8a)* (exit=0) | PASS |
| Web and job run no DDL; every role has its timeouts (D6, T4a) | `tests/db/test_roles.py::test_web_and_job_cannot_run_ddl` (10 cases)<br>`tests/db/test_roles.py::test_role_reports_its_timeouts` (4 cases)<br>`tests/api/test_error_shape.py::test_lock_timeout_is_a_retryable_503`<br>`tests/release/test_entrypoints.py::test_runtime_entrypoints_never_read_migration_url` (2 cases)<br>`tests/db/test_bootstrap.py::test_owner_url_is_never_an_argument` | PASS |
| Migrations never wait long for a lock (D2a) | `tests/release/test_release.py::test_real_migration_lock_fails_at_three_seconds_and_retries`<br>`tests/release/test_release.py::test_lock_timeout_fails_the_deploy_after_the_last_retry` | PASS |
| Destructive migrations need a restore point, every environment (D3; decision 19) | `tests/release/test_release.py::test_destructive_migration_refused_without_restore_point_in_every_environment` (4 cases)<br>`tests/release/test_release.py::test_restore_point_is_recorded_with_the_release` | PASS |
| Blocking index or constraint forms rejected on existing tables (D2b) | `tests/static/test_migration_safety.py::test_rejects_plain_index_on_existing_table`<br>`tests/static/test_migration_safety.py::test_rejects_validated_check_constraint_on_existing_table`<br>local gate *blocking-migration check (D2, D2b, D2c, D3)* (exit=0) | PASS |
| No model reads a setting; migration history never forks (D2f) | local gate *makemigrations --check (D2f)* (exit=0)<br>local gate *AST checks (W8a)* (exit=0)<br>`tests/static/test_ast_rules.py::test_models_may_not_read_settings` | PASS |
| Every error code is registered with its status (X5a) | `tests/platform/test_errors.py::test_unregistered_code_fails_at_import`<br>`tests/platform/test_errors.py::test_every_code_has_exactly_one_exception_class` | PASS |
| One error shape, with request_id (X7, X10a) | `tests/api/test_error_shape.py::test_domain_error_body`<br>`tests/api/test_error_shape.py::test_unhandled_becomes_internal_error_without_internals`<br>`tests/api/test_error_shape.py::test_unknown_url_uses_the_error_shape` | PASS |
| A named unique violation is the only caught integrity error (X11a) | `tests/platform/test_savepoint.py::test_other_constraint_reraises`<br>`tests/platform/test_savepoint.py::test_named_violation_is_treated_as_replay_and_outer_transaction_survives`<br>local gate *AST checks (W8a)* (exit=0) | PASS |
| No outbound HTTP inside atomic(); every call has timeouts (T1, T4) | `tests/platform/test_http.py::test_raises_inside_atomic_before_any_request`<br>`tests/platform/test_http.py::test_client_refuses_a_missing_timeout`<br>`tests/platform/test_http.py::test_request_refuses_disabling_the_timeout`<br>local gate *import-linter (T4, X6, D2d)* (exit=0) | PASS |
| Every job is registered, scheduled once per run, and monitored (N4, N4a) | `tests/concurrency/test_d5.py::test_two_schedulers_enqueue_each_run_once`<br>`tests/platform/test_jobs.py::test_no_periodic_enqueue_outside_the_scheduler`<br>`tests/platform/test_jobs.py::test_scheduler_refuses_to_start_without_rows`<br>`tests/platform/test_jobs.py::test_a_registered_job_without_a_row_is_stale`<br>`tests/platform/test_jobs.py::test_worker_runs_an_enqueued_job_end_to_end`<br>`tests/health/test_health.py::test_stopped_job_alerts_and_health_jobs_503_while_health_stays_200` | PASS |
| One open alert per (code, subject), written with its cause (N5) | `tests/platform/test_alerts.py::test_database_refuses_a_second_open_alert`<br>`tests/platform/test_alerts.py::test_alert_is_written_in_its_causes_transaction`<br>`tests/platform/test_alerts.py::test_notification_job_emails_open_unnotified_alerts_at_least_once`<br>`tests/concurrency/test_d5.py::test_alert_retry_on_two_connections_keeps_one_open_alert` | PASS |
| Rate limits hold across workers (A9) | `tests/concurrency/test_d5.py::test_rate_limit_holds_at_boundary_under_concurrency`<br>`tests/platform/test_ratelimit.py::test_increment_is_one_statement`<br>`tests/platform/test_ratelimit.py::test_pruning_removes_only_expired_windows` | PASS |
| Client IP only from trusted hops (A9b) | `tests/platform/test_client_ip.py::test_spoofed_xff_does_not_change_the_ip`<br>local gate *AST checks (W8a)* (exit=0) | PASS |
| Money is non-negative integer minor units, paired with a currency (M1, M1b, M2) | `tests/platform/test_money.py::test_negative_amount_refused_by_db`<br>`tests/static/test_ast_rules.py::test_money_rules`<br>local gate *AST checks (W8a)* (exit=0) | PASS |
| Exponents come from one ISO-4217 table (M1a, Q3b) | `tests/platform/test_money.py::test_exponents_come_from_the_iso_table` (9 cases)<br>`tests/api/test_money_schema.py::test_exponent_is_always_present`<br>`tests/platform/test_settings_registry.py::test_unknown_store_currency_fails_boot` | PASS |
| Lists are keyset-paginated on a public tiebreaker (Q2, Q2a, Q2b) | `tests/api/test_pagination.py::test_no_cursor_decodes_to_a_primary_key`<br>`tests/api/test_pagination.py::test_unknown_filter_or_sort_is_400` (3 cases)<br>`tests/api/test_pagination.py::test_tampered_cursor_is_400_or_stays_scoped` | PASS |
| Every route has an explicit schema; bodies are capped (Q3a, Q3c) | `tests/api/test_router_guard.py::test_route_without_schema_fails`<br>`tests/api/test_router_guard.py::test_all_registered_routes_pass`<br>`tests/api/test_body_cap.py::test_body_over_cap_is_413` | PASS |
| Health reveals only what N3 allows (N3, W3) | `tests/health/test_health.py::test_health_is_200_with_an_empty_body`<br>`tests/health/test_health.py::test_detail_refuses_a_wrong_token` (3 cases)<br>`tests/health/test_health.py::test_detail_with_token_reports_the_core_version` | PASS |
| No secrets or PII in logs or error reports (A12, X13a, X15) | `tests/platform/test_redaction.py::test_free_text_secrets_are_scrubbed_from_messages` (7 cases)<br>`tests/platform/test_redaction.py::test_named_fields_are_replaced_whole`<br>`tests/platform/test_redaction.py::test_sentry_event_is_scrubbed` | PASS |
| Timestamps are UTC; business days are store-local (L1, L1a, L2) | `tests/platform/test_business_day.py::test_business_day_job_runs_exactly_once_per_local_date_across_dst` (2 cases)<br>`tests/platform/test_business_day.py::test_failed_run_leaves_no_marker_and_reruns`<br>`tests/platform/test_business_day.py::test_timestamps_are_stored_in_utc`<br>`tests/concurrency/test_d5.py::test_business_day_marker_concurrent_insert_one_wins` | PASS |
| Language resolves in L3a order (L3, L3a) | `tests/platform/test_locale.py::test_order_language_wins`<br>`tests/platform/test_locale.py::test_user_preference_beats_accept_language`<br>`tests/platform/test_locale.py::test_accept_language_limited_to_installed_with_q_values`<br>`tests/platform/test_locale.py::test_falls_back_to_store_default` | PASS |
| Finished task results are pruned (decision 26) | `tests/platform/test_jobs.py::test_task_result_pruning_only_finished_past_retention`<br>`tests/platform/test_settings_registry.py::test_task_result_retention_out_of_range_fails_boot` | PASS |

## E. Not applicable in phase 1 (owner ruling C2)

A DoD item applies when the part of its rule it tests is in scope as the phase file narrows it.

| DoD item (tags) | Reason | Landing phase |
|---|---|---|
| Client-supplied currency has no effect (M3a, M4) | no cart or order takes a currency | 4 |
| Checkout reprices outside atomic(); tax adapter inside commit raises (M6a, T1) | no checkout or tax adapter | 5 |
| Zero- and three-decimal currencies round-trip through pricing and adapters (M1a) | no pricing or payment adapter; the API part is tested | 4 (pricing), 6 (adapters) |
| Every money column rejects a negative value (M1b), domain columns | no domain money column yet; test-only model tested | 4 onwards |
| Adjustment deltas and money columns (O10, M1b) | no OrderAdjustment | 6 (table) / 9 (writers) |
| Deleting a referenced user, product or variant is refused (O7) | no orders | 5 |
| Order number survives a forced collision (O6, X11a) | no orders | 5 |
| Zero-total cap is atomic across workers (S1c, A9, C1) | no placement | 5 |
| One OrderStatusLog per transition with a typed actor (S4) | no transitions | 5 |
| Cancellation approval permissions (S2, A6a, R1b) | no cancellations | 9 |
| COD collection adjustments (P13c, S1, O10, I1a, G7, A6a) | no COD | 10 |
| Difference attempt alongside the order's own attempt (P13a, O11, D5) | no attempts or adjustments | 9 |
| Second awaiting_payment adjustment refused (P13a, O11, D5) | no adjustments | 6 (index) / 9 |
| Permission and second approval per refund event (R1c, R1b, A6a) | no refunds | 8 |
| StockMovement has no FK to its cause (C8a, I8, O7) | no movements | 2 (movement) / 5 (order delete) |
| Two checkouts on one cart make one order (C12a, D5) | no checkout | 5 |
| Account message recipient and language (T2b, L3a, A1c) | no customer notifications | 3 |
| Tampered cursor returns nothing the caller could not see, object level (Q2a, A6) | the test endpoint scopes by a header, not by a principal | 3 |
| No response contains an internal pk; cart lines and order items by public id (Q3a) | no carts or orders; the pk part is tested | 4, 5 |
| A cart over 100 lines or a quantity outside 1..MAX_LINE_QUANTITY is 400 (Q3c) | no carts; the body cap is tested | 4 |
| out_of_stock names lines (C4b, X7, Q3a) | no checkout | 5 |
| A guest order attaches regardless of email case (A1a) | no orders; case-insensitive uniqueness is tested | 5 |
| Deactivated user's access token rejected (A4b) | no JWT; only the column and the bump | 3 |
| Same 404 for inaccessible and missing objects (A6, X9) | no customer-owned objects | 3 |
| Each privileged action refused without its named permission (A6a), actions other than manage_settings | the actions do not exist yet | stock 2; review, payment events 6; refunds 8; cancellation, addresses, shipments, delivery, receipt, returns 9; cash 10 |
| Shipment, delivery and receipt permissions (A6a, S8) | no fulfilment | 9 |
| Offline refund payout needs collect_cash (A6a, R1) | no refunds | 8 |
| Logs strip guest and cart tokens, card data, raw payment payloads (A8b, A12, X15) | those tokens and payloads do not exist; generic secrets and tokens are tested | 4 (cart), 5 (guest), 6 (payments) |
| Rate limits at the A9a default policies per endpoint (A9, A9a) | no endpoint policies yet; the store is tested | 3 onwards |
| Provider toggle change at runtime (F1c) | no providers registered | 6 |
| Bare save() refused on order, payment, refund (D7b) | no such tables; governed probe and SettingChange tested | 5, 6, 8 |
| Retention role deletes only retention-governed rows (D7) | no retention job | 11 |
| Discount values and currency (G1a, M2) | no discounts | 4 |
| Snapshot column NULL on older orders (D2e) | no snapshot column | first snapshot column added to a table holding orders (6 or later) |
| DB refuses bad adjustment or document transitions (D7, O10, I3, I7) | no adjustments or documents | 5 (invoice) / 6 (adjustment) |
| confirmation_token unique per cart (D5, C10, M6) | no checkout | 5 |
| price_changed / out_of_stock / discount_not_applicable carry details (X7, X10a) | codes not registered yet; request_id on every body is tested | 4, 5 |
| price_changed carries the G6 reason (X7, X5a, G4) | no discounts or checkout | 5 |
| Failed-attempt limits after pruning (V1a, A9) | no attempts | 7 |
| Concurrent COD placements at the cap (V8, S5, D5) | no COD | 10 |
| Retention job, aggregates, erasure, consent, resolved-alert pruning (I8, I8a, D6, O7, I10b, I10, C8a, N5, I11) | no retention job | 11 |
| Day-boundary reports (L1) | no reports; the business-day helper is tested across DST | first report job |
| Invoice renders in the order language, bilingual when required (L3) | no invoices | 5 / 11 (bilingual) |
| Deployment adapter for a core-only port is rejected (W2a) | no core-only port (owner ruling C2) | 4 (tax calculator port) |
| Upgrade-path gate and port-signature diff (D2, W4a) | first release | 2 (0.2.0) |

## F. Skipped tests

None. `pytest -v -rA` reported 390 results, all PASSED; no test was skipped, xfailed or errored.

## G. Tests not cited above

101 of 283 test functions are supporting tests not cited in a row (all PASSED):

- `tests/accounts/test_admin_otp.py::test_login_with_device_and_token_reaches_admin`
- `tests/accounts/test_create_staff.py::test_joins_named_groups`
- `tests/accounts/test_create_staff.py::test_password_is_never_an_argument`
- `tests/accounts/test_create_staff.py::test_weak_password_is_refused_and_nothing_is_created`
- `tests/accounts/test_email.py::test_lookup_by_any_case_finds_the_account`
- `tests/accounts/test_email.py::test_normalize_trims_and_lowercases_whole_address`
- `tests/accounts/test_email.py::test_stored_value_is_normalized_on_save`
- `tests/accounts/test_permissions.py::test_manage_settings_is_in_no_default_group`
- `tests/accounts/test_permissions.py::test_require_refuses_inactive_users`
- `tests/accounts/test_token_version.py::test_new_user_starts_at_zero`
- `tests/admin/test_admin_query_counts.py::test_change_page_query_count_is_constant`
- `tests/admin/test_admin_query_counts.py::test_changelist_query_count_is_constant`
- `tests/admin/test_admin_query_counts.py::test_every_registered_admin_has_a_builder`
- `tests/api/test_body_cap.py::test_body_at_cap_is_accepted`
- `tests/api/test_error_shape.py::test_rate_limited_carries_retry_after_and_details`
- `tests/api/test_pagination.py::test_allowlisted_filter_works`
- `tests/api/test_pagination.py::test_no_total_count`
- `tests/api/test_request_id.py::test_request_id_is_random_and_returned`
- `tests/api/test_router_guard.py::test_route_returning_bare_dict_fails`
- `tests/api/test_router_guard.py::test_schema_exposing_id_fails_even_nested`
- `tests/db/test_bootstrap.py::test_command_module_reads_no_environment_or_settings`
- `tests/db/test_bootstrap.py::test_owner_url_prompted_without_echo_on_a_terminal`
- `tests/db/test_bootstrap.py::test_owner_url_read_from_stdin_when_piped`
- `tests/db/test_bootstrap.py::test_rerun_creates_no_role_and_returns_no_password`
- `tests/db/test_bootstrap.py::test_rerun_never_regrants_on_existing_tables`
- `tests/db/test_grants.py::test_frozen_table_allows_only_listed_columns`
- `tests/db/test_grants.py::test_named_columns_save_works`
- `tests/db/test_grants.py::test_no_auto_now_on_governed_models_unless_updatable`
- `tests/db/test_roles.py::test_migration_role_has_d2a_lock_timeout_and_no_statement_timeout`
- `tests/db/test_roles.py::test_migration_role_owns_schema_and_tables`
- `tests/db/test_roles.py::test_retention_role_reads_but_cannot_write_by_default`
- `tests/db/test_roles.py::test_web_and_job_timeouts_match_t4a`
- `tests/health/test_health.py::test_detail_query_count_is_constant`
- `tests/health/test_health.py::test_detail_refuses_a_staff_session_without_second_factor`
- `tests/health/test_health.py::test_detail_with_a_verified_staff_session`
- `tests/health/test_health.py::test_health_is_503_when_the_database_is_unreachable`
- `tests/platform/test_alerts.py::test_after_resolution_a_new_alert_opens`
- `tests/platform/test_alerts.py::test_failed_notification_is_retried_next_run`
- `tests/platform/test_alerts.py::test_subject_is_a_typed_pair_not_a_foreign_key`
- `tests/platform/test_alerts.py::test_unknown_code_is_refused`
- `tests/platform/test_business_day.py::test_local_date_of_a_utc_instant`
- `tests/platform/test_client_ip.py::test_ipv6_is_normalized`
- `tests/platform/test_client_ip.py::test_missing_or_garbage_falls_back_to_remote_addr`
- `tests/platform/test_client_ip.py::test_one_trusted_hop_uses_the_address_the_proxy_saw`
- `tests/platform/test_client_ip.py::test_two_hops`
- `tests/platform/test_errors.py::test_rate_limited_carries_retry_after`
- `tests/platform/test_errors.py::test_registry_starts_with_the_phase_1_codes`
- `tests/platform/test_errors.py::test_undeclared_details_are_refused`
- `tests/platform/test_http.py::test_default_timeouts_are_all_set`
- `tests/platform/test_http.py::test_works_outside_a_transaction`
- `tests/platform/test_jobs.py::test_daily_schedule_is_in_utc`
- `tests/platform/test_jobs.py::test_every_registered_job_has_a_schedule_row_after_release`
- `tests/platform/test_jobs.py::test_failed_run_records_start_only`
- `tests/platform/test_jobs.py::test_nothing_is_enqueued_before_commit`
- `tests/platform/test_jobs.py::test_phase_1_jobs_are_registered`
- `tests/platform/test_jobs.py::test_run_records_start_and_success`
- `tests/platform/test_jobs.py::test_staleness`
- `tests/platform/test_jobs.py::test_sync_is_idempotent`
- `tests/platform/test_jobs.py::test_task_result_pruning_is_registered`
- `tests/platform/test_jobs.py::test_tick_enqueues_each_due_job_once_and_advances`
- `tests/platform/test_locale.py::test_each_language_has_a_direction`
- `tests/platform/test_locale.py::test_uninstalled_preferences_are_skipped`
- `tests/platform/test_money.py::test_table_has_only_three_letter_codes`
- `tests/platform/test_money.py::test_unknown_currency_raises`
- `tests/platform/test_notification_contract.py::test_configured_adapter_must_implement_the_port`
- `tests/platform/test_notification_contract.py::test_default_adapter_is_core_smtp`
- `tests/platform/test_ratelimit.py::test_enforce_raises_rate_limited_with_retry_after`
- `tests/platform/test_ratelimit.py::test_policy_declaration_is_validated`
- `tests/platform/test_ratelimit.py::test_principal_is_never_stored_in_clear`
- `tests/platform/test_ratelimit.py::test_windows_and_principals_are_independent`
- `tests/platform/test_redaction.py::test_dates_and_ids_survive`
- `tests/platform/test_redaction.py::test_settings_wire_the_filters_on_every_handler`
- `tests/platform/test_runtime_settings.py::test_admin_change_view_changes_setting_with_permission`
- `tests/platform/test_runtime_settings.py::test_kill_switch_row_is_seeded_off`
- `tests/platform/test_runtime_settings.py::test_no_op_change_writes_no_audit_row`
- `tests/platform/test_runtime_settings.py::test_provider_kind_refused_without_registered_provider`
- `tests/platform/test_runtime_settings.py::test_provider_toggle_without_key_refused_by_db`
- `tests/platform/test_runtime_settings.py::test_reason_is_required`
- `tests/platform/test_runtime_settings.py::test_unknown_kind_refused`
- `tests/platform/test_savepoint.py::test_retries_are_bounded`
- `tests/platform/test_settings_registry.py::test_default_language_must_be_installed`
- `tests/platform/test_settings_registry.py::test_demo_may_run_without_error_tracking`
- `tests/platform/test_settings_registry.py::test_every_setting_declares_change_class_and_type`
- `tests/platform/test_settings_registry.py::test_secret_values_never_appear_in_boot_errors`
- `tests/platform/test_settings_registry.py::test_task_result_retention_defaults_to_seven_days`
- `tests/platform/test_settings_registry.py::test_test_env_is_valid`
- `tests/release/test_entrypoints.py::test_command_roles_follow_the_owner_ruling`
- `tests/release/test_entrypoints.py::test_wsgi_entrypoint_declares_web`
- `tests/release/test_release.py::test_non_destructive_needs_no_restore_point`
- `tests/release/test_release.py::test_other_database_errors_are_not_retried`
- `tests/release/test_release.py::test_production_destructive_migration_needs_verified_restore_point`
- `tests/release/test_release.py::test_restore_point_accepted_and_returned_outside_production`
- `tests/release/test_smoke_and_seed.py::test_seed_demo_creates_one_staff_user_per_group_and_is_idempotent`
- `tests/release/test_smoke_and_seed.py::test_smoke_script_needs_the_token_in_the_environment`
- `tests/static/test_migration_safety.py::test_accepts_concurrent_index_in_non_atomic_migration`
- `tests/static/test_migration_safety.py::test_concurrent_index_needs_atomic_false`
- `tests/static/test_migration_safety.py::test_flags_type_change_as_destructive`
- `tests/static/test_migration_safety.py::test_new_table_may_use_plain_forms`
- `tests/static/test_migration_safety.py::test_not_null_column_without_db_default_is_unsafe`
- `tests/static/test_migration_safety.py::test_rename_in_place_is_unsafe`
- `tests/static/test_migration_safety.py::test_runsql_rewrite_is_destructive_but_revoke_is_not`

## H. Summary

- PARTIAL (gap noted): 1
- PASS: 63
- PASS (locally); CI pending: 4
- PENDING: 1
- inv PASS: 32
