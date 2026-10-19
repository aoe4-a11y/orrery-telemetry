# Hermes adapters

## Thin native launch

`thin_config.py --input INPUT --out PLAN` generates an upstream Hermes command,
configuration and environment references without invoking a credential helper.
`validate_input(document)` is the read-only admission used by the standard
launcher and catalog. It imports no Hermes code and starts no subprocess.

The standard launcher supplies the registered identity, product-generated MCP
configuration, shared rendered Codex instructions and the actual working directory.
The generator selects the installed committed executable and a custom provider
with native `key_cmd`; provider credentials remain Hermes's responsibility.
Optional model and helper selections must belong to the selected backend's
configured formal model IDs. An omitted effort leaves the native default intact.
The helper model applies to auxiliary tasks and delegation on that same provider.

Memory and skills persist in the fixed backend profile. Each child uses the
official `HERMES_MANAGED_DIR` overlay for its MCP entries and instructions;
profile configuration is not swapped or cloned. Product skills are links to
their canonical source, and existing unowned skills are never overwritten.
The native input queue uses `busy_input_mode=queue`. The initial prompt uses
`chat --query-file`; empty input opens the normal interactive CLI. No request,
output-token or session-lifetime limit, native-command ban, egress preload or
usage evaluator is added by this entry.

`thin_guard.py` adapts native pre-tool events to the common registration,
credential-read and acquired-reservation hooks. Only their exit 2 is a veto,
matching the ordinary hook contract. Generation checks the plugin file and
configuration statically; it does not import or verify runtime registration.
Explicit MCP selections that cannot be represented are rejected. Turning off
MCP inheritance disables unselected configured servers; profiles with enabled
third-party plugins are rejected in that mode because portable plugins can
append servers after configuration loading.

The plugin saves the native session-start event in `native-session.json` under
the child's existing state directory. Delegated sessions cannot overwrite it.
An explicit `resume_session_id` becomes native `--resume`; no shared MRU is used.
Missing resume metadata does not prevent startup. Standard launcher cleanup,
Mail delivery and process observation own the lifecycle.

The sections below describe the older managed runner and its compatibility
fixtures; their additional policies do not apply to the thin native entry.

The managed controller contract is [managed-spawn-contract.md](../../docs/managed-spawn-contract.md).
The pinned Hermes source is `d923a5eb487a17c0a68801bba9ef0f56c81040a8`.
The adapter advertises native conversation support after its offline acceptance gate.
Legacy three-field controller inputs retain their explicit batch compatibility path.

## Continuing native conversation

`managed_lifecycle.py` exposes `prepare`, `start`, `status`, `finalize` and `clean`.
The controller supplies its existing `run` and read-only `whois` context. This
adapter does not create a different Mail connection or fetch a parent's inbox.
HTTP attempt IDs and runner attempt IDs remain separate.

New task inputs carry `task_mode` and `report_policy`. An empty conversation opens
an idle native pane; an optional prompt seeds the first turn. An explicit assignment
requires a prompt; file scope and expected artifact checks are optional. With no
scope, reads and reserved writes stay within the selected private worktree. With
scope, assignment paths are checked as well. `expected` accepts literal relative
paths with one `contains` or `sha256` check. No requested artifact is seeded.

The owned supervisor connects native input and output through a controlling PTY,
with private diagnostic capture. It calls the same `cli.main` used by Hermes's
chat command, using the existing committed dependency interpreter. A completed
turn or assignment report does not terminate the process. No request/output cap
or runtime deadline is supplied by default. An explicit trial config may provide
a positive `provider_request_limit` or a `task_timeout_seconds` test deadline;
request timeout and runtime lifetime are distinct.

`status` derives readiness from the actual process's loaded guard, authenticated
product probe, preflight and one-time owned credential receipt. A wrapper exit is
not readiness. Terminal status requires the supervisor's actual runtime exit.
Activity and latest-turn data come from the native chat result, not displayed text.
An early credential failure cannot reuse the preceding turn's successful result.

Conversation success is not applicable. Assignment/pane checks binding, a completed
turn, provider evidence and any requested artifacts. Assignment/mail additionally
requires the product's verified send receipt to the real parent; an available parent
capture must also agree. A confirmed report is saved once in
`task-reports/<task_id>.json`, including artifact hashes, usage sequence and Mail
receipt references. Subsequent free turns do not re-evaluate or overwrite it.

Parentless sessions retain the product's normal Mail tools, including inbox and
ordinary messages to other agents. Report policy controls completion evidence,
not communication permission. Startup compares the actual native MCP roster with
the authenticated product schema. Tools are exposed eagerly; the separate tool
search bridge is not supported in this segment.

## Persistent profiles and private attempt configuration

Profiles remain fixed by child kind, retaining memory, skills, curator and sessions.
The installed root and dependencies are shared. Each interactive attempt owns its
`runtime-profile.json`; Hermes's config-path resolver is redirected only inside that
process. `HERMES_HOME` and memory/session/skill paths stay on the fixed profile.
MCP/token references and user-selected settings cannot overwrite another attempt's
config. Existing profile initialization is serialized; initialized plugin files are
verified and reused. A legacy profile must have confirmed retirement before its
first migration to the shared layout. No profile is copied from the live home.

The pinned source supports multi-process persistence: SQLite WAL and write retry
in `hermes_state.py`, file locks plus reread/atomic writes in
`tools/memory_tool_store.py`, and per-skill process locks in
`tools/skill_manager_tool.py`. The controller may remove its temporary
`profile_busy` restriction only after the interactive acceptance gate is integrated.
Other profile selectors and external skill directories remain confined to the
current profile. Installer-owned `profiles` symlinks require the install receipt's
exact persistent sibling target; manual/live/foreign links remain rejected.

Use custom provider names that do not collide with Hermes built-ins: for example,
backend ID `deepseek` can use the private provider name `deepseek-api`. Keep the
configured model, endpoint, transport and Keychain reference. `configure` reads the
pinned registry as data and returns `provider_name_collision` before profile/proxy
writes on a collision. Never fix this by exporting a credential environment value.
The installer provisions runtime references; operator templates supply these
non-colliding names outside the public repository.

## Reservations, credentials and provider evidence

Conversation reads require the worktree root; each write synchronously acquires an
exact-file reservation through the plugin's existing `call_mcp` connection, validates
the real owner/path/expiry, runs the guard, then releases it. Formal assignments also
apply declared scope. Private profile memory/skills retain their native locks and
are not redirected into the source worktree. Every real grant, including partial
responses, is retained in `reservation-ledger.json`; successful releases are recorded.
An unresolved RPC intent cannot become proof of an empty reservation inventory.
Expiry, conflict, missing guard and root escapes deny before writing.

Managed startup selects `credential_mode=owned-once`. The owned inference process
executes the validated Mac Keychain reference once after gates pass. Main and all
auxiliary clients reuse its in-memory command-token provider. No provider key enters
an environment, argv, config or hook/MCP child. The same bytes scan diagnostics before
exit; later commands do not reacquire the key. Missing scan evidence keeps cleanup
incomplete. Owner-token handoffs are read only by product helpers.

Only the chosen backend's configured Messages or Chat Completions endpoint is allowed.
Main and auxiliary routes share that policy, with empty fallback chains. Raw HTTPX
SSE/JSON is observed before SDK normalization: original usage and a valid terminal
boundary are required. Missing/null/interrupted usage blocks the next inference.
A later close/read failure overrides earlier positive usage evidence. Saved audit
contains counts, sequence/binding and safe destination/source positions, without
headers, bodies, keys, query strings or exception contents.

The current profile/source must have no dotenv files; absent candidates are checked
without opening them, and existing/dangling dotenv reads are denied. Metadata fetchers
honor the disabled runtime catalog and leave unknown prices unknown. Context overrides
are optional and do not imply output limits. Effort capability remains unknown for
initial Hermes routes; a setting resolver does not prove model capability.

Before native import, read-only PM selection and site-package checks reject recovery
markers or a missing committed environment. `HERMES_DISABLE_LAZY_INSTALLS=1` alone
does not suppress Hermes's independent early-recovery gate. Repair/install belongs to
the explicit operator path. Startup never invokes repair to get past this gate.

The first segment supports guarded file tools, normal product Mail and private
memory/skills/curator. Shell/web/image/model-switch/resume/export and other native
shortcuts need their own guard integration; they are explicitly unsupported here,
not permanent product prohibitions. Native `@file` expansion stays literal so it
cannot read outside tool dispatch; file-backed paste references also stay literal.
The direct pane remains available for later input;
automatic Mail-to-model followup is a separate stage.

## Closing and explicit compatibility commands

On actual runtime close, finalize observes owned-group absence, checks diagnostics,
releases the union of boot and dynamic grants, retires through the product cleanup
hook and confirms the same child's `whois`. `clean` removes handoff files after
successful evidence, preserving artifacts, reports and profile memory. Empty
conversation inventories require a real zero-release observation, not a fabricated
acquisition. Unknown/partial startup or reservation state remains pending.

A confirmed never-started, reservation-free attempt may close as
`not-started-retired` without inventing process/group/release evidence. The operator
can use `dashboard/managed_spawn.py --job JOB --finish-unstarted` after deploying a
compatible version. Task failure remains distinct from successful cleanup.

`runner.py` has explicit commands for init, registration, configuration, probe,
preflight, start, status, completion, stop, release, retirement and cleanup. `init-task`
without input now creates an empty conversation. `init-batch --input TASK_JSON` is an
explicit answer-and-exit compatibility path. Only `selftest-task` creates the original
reserved canary; ordinary preparation never supplies that trial task. The older
Mail-only `init` pilot remains explicit and separate from interactive acceptance.
Private machine config, absolute runtime paths and credential references stay outside
the repository. Only canonical product preregistration, `child_tools.py` generation
and its bound stdio proxy are used. Do not retry partial identity creation.

Installer generation v2 writes the pinned upstream install stamp with external
update ownership and validates its receipt/hash. Runtime version import then
needs no git process. Existing v1 generations are retained; after installation,
the operator must point the private template's runtime roots to the new generation.
The installer does not rewrite that template automatically.

## Offline checks

With separately prepared dependencies, run all Hermes fixtures serially:

```sh
scripts/check-hermes.sh --config PRIVATE_RUN_CONFIG --out RESULT_JSON
```

The check resolves the committed interpreter and uses a temporary HOME/offline cache.
It does not install/repair dependencies or use actual credentials, provider API or
Mail registration. Results contain `success`, `tests_run`, `failures`, `errors`,
`skips`, `allowed_skip_reasons` and `unapproved_skips`. Approved reasons are exact
strings; the default list is empty, so every skip fails acceptance.

The original `offline_probe.py` remains a separate dummy-key source/tool/MCP fixture.
Its local stdio server is not ORRERY Mail. Offline evidence never certifies live
backend authentication or operator acceptance.
