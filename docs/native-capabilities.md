# Native context and helper models

Thin dsh/Hermes launch uses the existing agent `ctx_used` / `ctx_window` fields
and existing spawn catalog `models[].harnesses[].helper_models` shape. There is
no additional provider endpoint or credential lookup in these readers.

## Activity classification boundary

API 24 observes native activity from the same captured pane as context.
`dashboard.harness_activity.parse_activity(text, program)` returns `work`,
`question` or `ask` only from supported current controls. A question or approval
needs both its panel title and operation hint near the bottom. These modals
take priority over a busy hint because native turns can remain working while
waiting for the user. The context parser itself does not infer activity.

Supported formats are dsh-tui 0.16.1's English/Chinese approval and question
panels (including folded questions), its interrupt footer, and Hermes
d923a5eb's bundled English/Japanese approval, clarify and busy-composer hints.
Missing, hidden, incomplete, offscreen or unsupported localized controls stay
`act_state: null`. Each new capture replaces the previous observation; a missing
control does not preserve the old activity. Display text is not authenticated
telemetry and can be imitated by terminal output.

Idle is not inferred from absence. Hermes chooses a localized random empty
composer placeholder; dsh's idle hint changes with selection, help, hover and
minimal UI. A generated config alone does not make either an unconditional idle
marker. Thus native `wait` remains unsupported: null means unknown, not idle,
finished or ready. Activity never changes process liveness or stop eligibility.
The existing Claude/Codex classification is unchanged. No new watcher, native
patch, status file or provider call is introduced.

## Context

`dashboard.harness_context.parse_context(text, program)` receives an already
captured pane and the actual runtime program (`dsh` or `hermes`). It observes
the last twelve lines only and returns context percentage and display window.
It does not determine process lifetime, activity, model identity, billing or
exact token counts. Hidden or truncated status returns nulls, never zero usage
or a window guessed from a model name. The normal Claude/Codex parser remains
separate. Callers must also avoid applying its model-name window fallback to
native unknown results.

Source formats at the pinned runtime versions:

- dsh 0.2.1-rc.2 / dsh-tui 0.16.1: `tuiDisplayPrefs.js:72`
  `formatContextUsage`, rendered by `screens/StatusLine.js:161–197`:
  `ctx 19% (24k/128k)` or `ctx 24k/128k (19%)`. This is the TUI's current
  occupancy reading, not lifetime input/output usage. dsh's fractional reading
  is rounded to the existing integer percentage; over-capacity stays visible.
- Hermes d923a5eb: `hermes_cli/cli_status_bar_mixin.py:1017–1129`, the native
  wide status row: `☤ Qwen │ ~24K/128K │ [██░░░░░░░░] ~19%`. Narrow/medium
  rows without a complete capacity reading remain unknown. Native `~` readings
  are estimates; preserving a visible percentage does not make them exact.

These are observations of a terminal display, just like the existing native
providers, not authenticated telemetry. Localized/custom/hover displays without
the supported footer shape can remain unknown. Old offscreen transcript text
does not supply context. No extra watcher, session file or model API is used.

## Model and helper catalog

The operator-owned manifest declares `backends[backend].models` as formal model
ID strings. If absent, its single `model` is the only configured ID. Main and
helper selections share this same backend set. Populating a live manifest is
an operator deployment step, not catalog discovery.

`dashboard.harness_helpers.model_rows(manifest, backend_id, *, selections,
statuses, product_root)` projects public model rows. The internal maps use
`(model, harness)` keys: successful shared `hooks.harness_child.selection()`
results and that exact pair's availability/I5 fields. The catalog caller checks
each pair independently; it must not copy the primary model's effort metadata
to other models. Missing/unavailable pairs expose unknown effort metadata and
only `same` as helper. The shared selection cache owns subprocess budgets.

Alternate helpers require literal `HELPER_MODEL_CONTRACT = 1` in the selected
`integrations/<harness>/thin_config.py`. The catalog reads this via AST and
does not import the generator. The helper list is the intersection of configured
same-backend IDs, public model IDs and successful selections on that harness.
Old or unavailable generators expose `same` only. Public output contains only
model IDs/labels and capability fields, never runner paths or configuration.

The catalog's `validate_helper_model(value, choices)` is also the POST
validator: omitted means `same`, foreign/undeclared IDs raise
`invalid_helper_model`. The common launcher carries explicit `--helper-model`
into generator INPUT. Each generator validates the same backend set again.
No second provider or credentials are inferred. dsh projects its subagent model;
Hermes projects auxiliary task and delegation models. Exact generator mappings
belong to the shared thin-generator contract and their implementations.

The New Agent screen folds the selected main ID into `Same as main` for display, so a
single-model backend does not gain a redundant helper control. This does not
remove its formal ID from the backend's accepted set.
