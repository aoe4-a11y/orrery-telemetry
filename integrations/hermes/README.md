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
Each child uses a private provider name and minimal route in its overlay, so
old endpoint aliases, inline keys and named credential pools in the persistent
profile cannot override the selected route. The profile and its auth store are
not rewritten or copied. Legacy model credential pointers are cleared only in
the child overlay; memory and skills remain in the fixed backend profile.
Auxiliary tasks and delegation use that same private provider, with old direct
endpoint and credential pointers cleared in the overlay. Existing helper
settings cannot pair the selected credential with a previous endpoint.
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

`thin_guard.py` adapts native pre-tool events to the common credential-read,
registration and acquired-reservation hooks, in that order. A failed check
blocks the tool with a fixed diagnostic, without exposing hook output.
An allowed hook's structured `systemMessage` warning remains visible; raw
stdout/stderr are not forwarded.
Successful native edits call the common reservation release hook. Both
checks and release run in the native tool's current directory.
Generation checks the plugin file and
configuration statically; it does not import or verify runtime registration.
Explicit MCP selections that cannot be represented are rejected. Turning off
MCP inheritance disables unselected configured servers; profiles with enabled
third-party plugins are rejected in that mode because portable plugins can
append servers after configuration loading.

The plugin saves the native session-start event in `native-session.json` under
the child's existing state directory. Delegated sessions cannot overwrite it.
An explicit `resume_session_id` becomes native `--resume`; no shared MRU is used.
An optional `native_profile_env` pin is checked using canonical paths before
creating files or links; a changed profile is rejected.
Missing resume metadata does not prevent startup. Standard launcher cleanup,
Mail delivery and process observation own the lifecycle.

## Installation and offline checks

Installer generation v2 writes the pinned upstream install stamp with external
update ownership and validates its receipt/hash. Runtime version import then
needs no git process. Existing generations and profile data are retained; after
installation the operator points the private template at the selected generation.
The installer does not rewrite that template automatically.

With separately prepared dependencies, run all current Hermes fixtures serially:

```sh
scripts/check-hermes.sh --config PRIVATE_RUNTIME_TEMPLATE --out RESULT_JSON
```

The check reads PM facts to select the committed dependency interpreter, without
importing Hermes or running install/repair. It uses a temporary HOME and offline
cache. Missing dependencies fail setup rather than being accepted as a skip.
Results contain `success`, `tests_run`, `failures`, `errors`, `skips`,
`allowed_skip_reasons` and `unapproved_skips`. Approved skip reasons are exact
strings; the default list is empty, so every skip fails acceptance.

Fixtures cover native configuration and hook dispatch, main/helper credential
routing, generation ownership and version stamps. They use isolated profiles and
synthetic credentials; they do not certify live authentication or operator
acceptance. Standard spawn, native resume and common cleanup retain their own
integration tests. The former managed controller, private-copy runner, provider
allowlist/usage evaluator and separate lifecycle status are removed.
