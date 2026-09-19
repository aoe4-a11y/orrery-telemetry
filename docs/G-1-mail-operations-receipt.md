# G-1 mail operations receipt (station 8380, lane G-1)

台帳: R-058 D4・R-017・M-005・M-006・M-011・M-022・M-023・P-015. Worker
BlackTesla (claude-opus-5), parent RoseFaraday, head PinkTesla. Worktree
`orrery-telemetry-wt-g1-reply-ack`, branch `codex/g1-reply-ack-override`,
base `e5039ff`. Production resources were read only: no deploy, restart,
install, log deletion/truncation or DB write happened. Reviews 8400, 8408,
8416, 8422 and 8435 are folded in.

Vocabulary used for every claim: **observed** = measured on this machine with
the command named; **inferred** = follows from the current source plus an
observed fact; **unknown** = no evidence either way. Evidence files (suite
outputs, tables, rate) are kept outside the repo at
`/Volumes/DevSSD/agentstack-logs/g1-mail-repair-20260920/`.

## 1. `reply_message` ack_required override (TASK1)

`packages/agentstack_mail/src/agentstack_mail/app.py`

- New optional trailing parameter `ack_required: Optional[bool] = None`; every
  pre-existing parameter is unchanged (signature-guard test).
- `_resolve_reply_ack_required`: explicit bool wins → else
  `AGENTSTACK_REPLY_ACK_DEFAULT`: `inherit` (default) copies the original
  flag; `false` — also `0`, `no`, `n`, `f`, case-insensitive, whitespace
  trimmed (the same false vocabulary as `config._bool`) — sends no ack demand;
  every other value, `true` included, behaves as `inherit`. Read through the
  package's decouple config so the service `.env` and the process env are
  both honoured. Docstring, `docs/configuration.md` and
  `docs/configuration.en.md` state the same rule.
- Resolved once before routing and passed to **both** `_deliver_message`
  calls (local and cross-project), so the branches cannot disagree.
- `packages/agentstack_mail/fixtures/live-tools-list.json`: the frozen
  compatibility contract gained exactly the new property
  (`ack_required: anyOf boolean|null, default null`, 11 added lines, no other
  change; parent 8422 authorised).

Tests `packages/agentstack_mail/tests/test_reply_ack_override.py` (private
SQLite/archive/signals under `tmp_path`; no production API traffic):

```
PYTHONPATH=. .venv/bin/python -m pytest -q packages/agentstack_mail/tests/test_reply_ack_override.py
→ 13 passed, exit 0
PYTHONPATH=. .venv/bin/python -m pytest -q packages/agentstack_mail/tests/test_runtime_contract.py
→ 10 passed, exit 0
```

Cases: inherit true/false, env `inherit`, env `false`, ` FALSE `, `0`,
`true` (= inherit, not force-on), env `false` + explicit `true`, explicit
`false` over inherited `true`, explicit `true` over inherited `false`,
unknown value → inherit, signature guard, both-branches guard. Mutation
check (observed): with the helper forced back to pure inherit, 5 of the
original 11 fail.

**Limit:** the cross-project branch is verified by a *source* assertion
(both `_deliver_message` calls use `reply_ack_required`; the old
`ack_required=original.ack_required` is gone), not end to end — an approved
`AgentLink` fixture (cf. `test_pending_decision_d3.py`) would be needed.

## 2. Threadless `Re:` messages (TASK2, read-only DB audit)

Source: `sqlite3 -readonly ~/.agentstack/mail/storage.sqlite3`; predicate
`subject LIKE 'Re:%' AND created_ts >= '2026-09-12'` (`created_ts` is UTC
text). Columns read: `messages.id, sender_id, thread_id, subject,
created_ts, project_id`, `agents.name`. No bodies.

Totals (snapshot 2026-09-19T14:53:53Z): 614 rows, 310 `thread_id IS NULL`,
304 threaded — the task baseline 609/310 plus 5 threaded rows. UTC 09-13:
317 / **244** threadless. Per-day totals are the row sums in the table below.

### 2.1 Full table — sender × UTC day × route-evidence class

Snapshot 2026-09-19T15:14:34Z (616 rows; 2 threaded rows arrived after the
first snapshot). Re-aggregable from `route_table.psv` in the evidence dir or
from the SQL in §2.2.

| sender | day (UTC) | A | B | C | D1 | D2 | E | total |
|---|---|---|---|---|---|---|---|---|
| BriskHopper | 2026-09-12 | 11 | 0 | 1 | 0 | 1 | 0 | 13 |
| BriskHopper | 2026-09-13 | 12 | 0 | 0 | 0 | 0 | 0 | 12 |
| BriskHopper | 2026-09-14 | 8 | 0 | 0 | 0 | 0 | 0 | 8 |
| BriskHopper | 2026-09-15 | 13 | 0 | 0 | 0 | 1 | 0 | 14 |
| BriskHopper | 2026-09-17 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| KindPasteur | 2026-09-13 | 10 | 0 | 0 | 0 | 0 | 0 | 10 |
| KindPasteur | 2026-09-14 | 3 | 0 | 0 | 0 | 1 | 0 | 4 |
| KindPasteur | 2026-09-15 | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| KindPasteur | 2026-09-19 | 5 | 0 | 0 | 0 | 0 | 0 | 5 |
| PinkTesla | 2026-09-17 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| PinkTesla | 2026-09-19 | 0 | 0 | 12 | 0 | 1 | 0 | 13 |
| PolarWatt | 2026-09-13 | 18 | 0 | 0 | 0 | 0 | 0 | 18 |
| PolarWatt | 2026-09-15 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| ProudTuring | 2026-09-12 | 1 | 4 | 3 | 0 | 0 | 0 | 8 |
| ProudTuring | 2026-09-13 | 131 | 1 | 4 | 65 | 0 | 0 | 201 |
| ProudTuring | 2026-09-14 | 0 | 130 | 5 | 0 | 1 | 0 | 136 |
| ProudTuring | 2026-09-15 | 0 | 59 | 1 | 0 | 0 | 0 | 60 |
| RoseFaraday | 2026-09-19 | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| RosyPascal | 2026-09-13 | 63 | 0 | 3 | 0 | 0 | 0 | 66 |
| RosyPascal | 2026-09-14 | 6 | 0 | 0 | 0 | 0 | 0 | 6 |
| RosyPascal | 2026-09-15 | 8 | 0 | 1 | 0 | 0 | 0 | 9 |
| RosyPascal | 2026-09-17 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| SolidFermi | 2026-09-12 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| SolidFermi | 2026-09-13 | 10 | 0 | 0 | 0 | 0 | 0 | 10 |
| SolidFermi | 2026-09-14 | 1 | 0 | 0 | 0 | 1 | 0 | 2 |
| SolidFermi | 2026-09-15 | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| SolidFermi | 2026-09-19 | 0 | 0 | 4 | 0 | 5 | 0 | 9 |
| **all** | 09-12..09-19 | **310** | **196** | **34** | **65** | **11** | **0** | **616** |

Classes (all **observed** from DB columns; the *route reading* column of
§2.3 is where inference starts):

- **A** `thread_id IS NULL`.
- **B** numeric `thread_id` = id of an existing message whose subject equals
  the row's subject with the leading `Re:` stripped (or equals it verbatim).
- **C** an earlier message already carries the same `thread_id`.
- **D1** `thread_id` = existing message id, and the subject has the form
  `<prefix starting with "Re:"> <that message's subject>` — the shape
  `reply_message(subject_prefix=…)` produces (7554-7558).
- **D2** `thread_id` = existing message id, subject not derivable from that
  *thread-root* message's subject (11 rows: PinkTesla 1, SolidFermi 6,
  BriskHopper 2, KindPasteur 1, ProudTuring 1). Because a reply inherits the
  root's `thread_id`, a `reply_message` to a *later* message in the same
  thread (whose subject differs from the root's) also lands here — tool
  route unknown.
- **E** anything else — 0 rows.

### 2.2 Code facts (observed in source, line numbers @e5039ff)

- `reply_message`: `thread_key = original.thread_id or str(original.id)`
  (7552), passed to both deliveries (7664/7694) and persisted verbatim by
  `_create_message` (3811). It **cannot** write a NULL `thread_id`. Its
  subject is always `<subject_prefix> <original subject>` (or the original
  subject when it already starts with the prefix), 7554-7558; the caller may
  choose `subject_prefix` but not a free subject.
- `send_message`: persists `thread_id` only when passed (6669); it never
  parses `Re:` nor infers a thread (6661-6667 only truncates long subjects).
  Any `thread_id`/subject combination can be produced with it.
- Other writers: `_deliver_message` is called from `send_message`
  (7355/7378), `reply_message` (7676/7706) and the contact intro (7900, fixed
  subject). Other writers in the repo: `grep -rn "INSERT INTO messages"
  dashboard/ scripts/ hooks/ bin/` → 2 hits, both in the docs-demo scripts
  (`scripts/dashboard-demo.py:601`, `scripts/dashboard-demo-reel.py:763`),
  which by their own header never touch the user's ORRERY Mail database; the
  dashboard's 3 `.py` files only read.
- Deployed service source `~/.agentstack/mail-service/candidates/95c1…/venv/
  …/agentstack_mail/app.py` is byte-identical to `e5039ff:app.py` (`diff
  -q`); the running server (pids 7517/7519, etime 4d20h) executes from that
  candidate (`ps`). Only that candidate/render exists (dir mtimes 2026-09-05);
  the `thread_key` line dates from 2026-08-06 (`git log -S`), app.py last
  changed 2026-08-28.

### 2.3 Route reading per class

| class | n | current-code inference | audit-log observation (09-12 → 09-15 03:03 JST) | remaining unknown |
|---|---|---|---|---|
| A | 310 | not `reply_message`; on this code only `send_message` without `thread_id` (or a non-MCP writer, none found) | sender-set level only (no row match): in the log window the non-head A senders (RosyPascal, PolarWatt, BriskHopper, KindPasteur, SolidFermi) appear with `send_message` calls and 0 `reply_message` calls; ProudTuring called both | which build served each row before 09-15 (no per-day deployment log; single-candidate layout is the only evidence); rows after 09-15 03:03 (8 rows: 09-17 ×1, 09-19 ×7) have no tool-log coverage |
| B | 196 | consistent with `reply_message` (default prefix) **and** with `send_message(thread_id=str(id), subject="Re: …")` | ProudTuring is the only `reply_message` caller in the log window; B rows are 194/196 ProudTuring | tool per row not determinable from the DB |
| C | 34 | consistent with either tool | — | same |
| D1 | 65 | consistent with `reply_message(subject_prefix="Re: …")` **and** with `send_message` | all 65 are ProudTuring 09-13, the day with 52 logged `reply_message` calls (JST day) and 75 `send_message` calls | same |
| D2 | 11 | not derivable from the thread root's subject; a reply to a later message in the thread or `send_message(thread_id=…)` both fit — route unknown | — | same |

Audit log: `~/.agentstack/mail-service/runtime/agentstack-mail.log`
(1,768,600,096 bytes, 11,211,123 lines, first/last `Timestamp` 2026-09-09
05:19:29 / 2026-09-15 03:03:42 local; `grep -a -A6 "MCP TOOL CALL STARTED"`
→ Tool/Timestamp/Agent fields only, saved as `toolcalls.txt`):

| tool (JST day) | 09-12 | 09-13 | 09-14 | 09-15 (→03:03) | callers |
|---|---|---|---|---|---|
| reply_message | 5 | 52 | 55 | 47 | ProudTuring only |
| send_message | 41 | 355 | 405 | 96 | SolidFermi 85/104/29, ProudTuring 75/94, RosyPascal 67/77, BriskHopper 57, KindPasteur 37, RoseFaraday 31/35, PolarWatt 30, … (09-13/09-14/09-15 counts) |

`MCP TOOL CALL FAILED` blocks: 60 total, 0 mention `reply_message`.

**Coverage gap (M-023):** the running server writes no tool log after
2026-09-15 03:13. Searched `~/.agentstack/mail-service/runtime/` (2 files:
the log above and `agentstack-mail-autostart.log`, 128 KB of
`agentstack-mailctl` lines only) and `~/.agentstack/runtime/*.log` (none in
the tool-call format). The JST log day and the UTC DB day overlap only
partially, so the two tables are not row-matched; they are compared as
sender sets.

**Conclusion (one line, scoped):** *procedure* — on the deployed code a
`Re:` row without `thread_id` is reproducible only by `send_message` without
`thread_id`; the logged sender usage in 09-12 → 09-15 03:03 JST (non-head A
senders: `send_message` only, 0 `reply_message` calls or failures) supports
that inference, while the route of each individual row remains unverified
(sender-set comparison, no row match); the 8 rows after the log window,
ProudTuring's own 132 A rows and any build not present as a candidate are
unverified; no server bug was found.

**Proposed remedy (not applied):** (1) seat/head procedure — reply with
`reply_message` (now with `ack_required=False` where R-017/P-015 say no ack),
or pass `thread_id` to `send_message`; (2) for later review, a
`send_message` warning when the subject starts with `Re:` and `thread_id`
is None. No backfill: the DB is not the inbox and the rows are correct as
sent.

## 3. Watcher re-scan loop (TASK3a, metadata only)

Read: `~/.agentstack/hooks/watch_agent_mail_signals.sh` (478 lines; equal to
repo `hooks/watch_agent_mail_signals.sh` @e5039ff except live lines 358-364,
the head per-message unlink), `org.huyuhutaru.orrery-mail-watcher.plist`,
`~/.agentstack/runtime/notify-state.json`, bounded samples of
`~/.agentstack/runtime/mail-watcher.log` (last 20,000 lines, line *classes*
and agent names only; no subjects or bodies reproduced).

**Code inference** (repo line numbers): main loop 457-470 → every
`SCAN_INTERVAL=30` s (52) `process_existing_signals` (436-444) `find`s every
`*.signal` (recursively, so `signals/.quarantine-20260909/` is included) →
`handle_signal_file` → `state_should_attempt` (107-127) says "attempt" for
any non-`success` entry once `RETRY_COOLDOWN=30` s (53) has passed → `log
"Signal: …"` (322) → `deliver_worker` → no tmux session →
`session_not_found` (369) and the signal file is kept. Destination: stdout
→ launchd `StandardOutPath` `~/.agentstack/runtime/mail-watcher.log`.

**Observed:**

- Signal files: 907 (901 per-message layout, 0 legacy, 6 under
  `.quarantine-20260909/`), 287 distinct agent names, 12 older than 24 h.
- `agents.retired_at IS NOT NULL`: 71 agents; **0** of them have a pending
  signal. All 286 sessionless agents with pending signals have
  `retired_at IS NULL` and no tmux session (`tmux ls` = 8 sessions, 1 of
  which has pending signals). This is retrying **unretired seats without a
  pane**, not resending to retired seats; a retired-only skip would not
  change today's emission at all.
- `notify-state.json` (5.0 MB, 17,821 entries): success 12,848 ·
  session_not_found 2,639 · head_no_pane 2,192 · modal_surface 142.
  Entries attempted in the last 300 s: 906, all `session_not_found`.
- Last 20,000 log lines: 19,553 `Signal:` lines, 434 `Watcher already
  running (PID 85749); exiting duplicate instance` (the second LaunchAgent
  `org.agentstack.mail-watcher`, KeepAlive, shares the log path), 14
  `Injected notification`. Top `Signal:` agents: PinkTesla 761, TanDarwin
  176, IcyLamarr 110, BraveNewton 110, JadeNewton 106 (291 distinct).
- Head skip: live line 355 compares to `${AGENTSTACK_HEAD_AGENT:-ProudTuring}`;
  the variable is absent from `~/.agentstack/env.sh` and from the watcher's
  environment (`ps -E 85749`, 0 hits), so PinkTesla (38 pending files) is
  treated as an ordinary paneless seat.
- **60 s measurement** (`stat -f %z` / `wc -l` before and after two 30 s
  sleeps; no watcher loop of my own): 2026-09-19T14:57:16Z → 14:58:16Z:
  **+606 lines, +109,448 bytes**; file 329,052,333 bytes / 1,866,494 lines
  at t1. Theoretical ceiling from the loop alone: 906 files ÷ 30 s × 60 s =
  1,812 lines/min; the measured 606 is a third of that. The gap
  (per-signal python start-ups in `state_should_attempt`, lease collisions,
  tmux time-outs, scan duration) was **not measured** — only the delta was.
  Extrapolation at the measured rate: ≈150 MiB/day; the file grew from 325
  MB (task text) to 329 MB during this station.

### 3.1 Proposed change (receipt only; live hook, repo hook and DB untouched)

Keeps the existing 30 s retry and the signal file, so a seat that regains a
pane is delivered on the very next scan exactly as today; only the repeated
`Signal:` line for a signal whose *previous* attempt already ended in
`session_not_found` is suppressed. A first attempt, any other outcome, and
the `Injected notification` line on success still log, so recovery stays
visible. Expected effect with today's 906 files: the ~600 lines/min fall to
the first-attempt lines only (new signals) — not measured, since it was not
run.

```diff
--- a/hooks/watch_agent_mail_signals.sh
+++ b/hooks/watch_agent_mail_signals.sh
@@ -119,9 +119,13 @@ entry = data.get(compound)
 if not entry:
     sys.exit(0)
 if entry.get("last_result") == "success":
     sys.exit(1)
 last_attempt = int(entry.get("last_attempt_epoch", 0) or 0)
 if int(time.time()) - last_attempt >= cooldown:
-    sys.exit(0)
+    # 2 = attempt again, quietly: the previous try already logged that this
+    # seat has no pane. 2026-09-19: 906 such files re-logged every 30 s.
+    # Delivery, cooldown and the signal file are unchanged.
+    sys.exit(2 if entry.get("last_result") == "session_not_found" else 0)
 sys.exit(1)
 PY
 }
@@ -303,7 +307,10 @@ handle_signal_file() {
     # `set -e` 下で `|| return` だと return が直前の exit code を継承して
     # 関数が non-zero で抜け、呼び出し元の while ループが止まる。
     # 早期スキップは `return 0` を明示してスクリプト継続を保証する。
-    state_should_attempt "$agent_name" "$msg_key" || return 0
+    local attempt_rc=0
+    state_should_attempt "$agent_name" "$msg_key" || attempt_rc=$?
+    # 1 = skip (delivered or still cooling down); 2 = attempt without the
+    # Signal: line; anything else (python crash) skips as before.
+    if [ "$attempt_rc" -ne 0 ] && [ "$attempt_rc" -ne 2 ]; then return 0; fi
@@ -319,7 +326,9 @@ handle_signal_file() {
     acquire_delivery_lease "$agent_name" "$msg_key" || return 0
 
-    log "Signal: ${agent_name} ← ${from} [${importance}]: ${subject}"
+    if [ "$attempt_rc" -ne 2 ]; then
+        log "Signal: ${agent_name} ← ${from} [${importance}]: ${subject}"
+    fi
```

Not adopted (kept for the record): raising the `session_not_found` cooldown
to 3600 s would cut the retries themselves, but delays a returning seat by up
to an hour — rejected by the parent (8416) as too costly.

Companion configuration notes for the head (no code): export
`AGENTSTACK_HEAD_AGENT=PinkTesla` in `~/.agentstack/env.sh` so the existing
head skip (355-366) applies to the current head; the duplicate LaunchAgent
`org.agentstack.mail-watcher` (KeepAlive, exits immediately, 434 of the last
20k lines) is a candidate for `bootout`; and `.quarantine-20260909/` (6
files) is still scanned.

## 4. Runtime log rotation (TASK3b, preparation only)

- `scripts/rotate_runtime_logs.sh` — `#!/bin/bash`, runs on /bin/bash 3.2;
  passes `tests/test_bash32_local_selfref.py` and
  `tests/test_stat_portability.py` (GNU `stat -c` first, BSD `-f` fallback).
  Size threshold 50 MiB (`AGENTSTACK_LOG_ROTATE_THRESHOLD_BYTES`), archives
  `NAME.log.1..KEEP` (`AGENTSTACK_LOG_ROTATE_KEEP`, default 3), depth-1
  `*.log` only, `--dry-run`.
  - Safety (8400): every archive slot is pre-flighted before anything
    changes — a symlink, directory or multiply-linked file in any slot, or a
    hard-linked source file, skips the whole file; the copy goes to a fresh
    `mktemp` file in the same directory and is renamed into slot 1, so no
    fixed temp name can pre-exist as a link; root and file symlinks and
    paths resolving outside the root are refused; subdirectories are never
    entered.
  - Lock (8435): `mkdir` is the only atomic step. **No stale recovery**: any
    existing lock, dead pid or not, fails closed with a message and exit 0;
    removing one is a manual head step. Release unlinks only this run's own
    pid file (lock not a symlink, pid equals `$$`) and `rmdir`s; foreign
    content is never moved or deleted.
- `scripts/launchd/org.agentstack.runtime-log-rotate.plist` — rootless
  LaunchAgent, daily 04:30, `Nice 10`, scope **`~/.agentstack/runtime` only**
  (8408; `mail-service/runtime` is not approved and not listed), own output
  `~/.agentstack/runtime/log-rotate.log`. Not installed. Deployment is the
  head's and needs both steps written in the plist comment: install the
  script to `~/.agentstack/hooks/rotate_runtime_logs.sh` **and** copy the
  plist (with `/Users/huyuhutaru` replaced by the real home — launchd does
  not expand `$HOME` in path keys) then `launchctl bootstrap`; dry-run first.
- Semantics stated in the script header: **50 MiB is the rotation
  threshold checked once per run, not a cap on the archive** — between daily
  runs a busy log overshoots (mail-watcher.log at ≈150 MiB/day would be
  rotated at ≈200 MiB); **copytruncate is not lossless** — bytes appended
  between `cp` and `: >` are dropped; launchd's O_APPEND writers continue at
  the new end, a non-O_APPEND writer leaves a NUL hole (both fixture-tested).
  The rotated jobs keep their current `StandardOutPath`.
- Tests `tests/test_rotate_runtime_logs.py` (stdlib, temp dirs only; an
  open append writer and an open non-append writer included):
  `python3 tests/test_rotate_runtime_logs.py` → 19/19 passed, exit 0;
  `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_rotate_runtime_logs.py
  tests/test_stat_portability.py tests/test_bash32_local_selfref.py` → 22
  passed.
- Current sizes (observed, untouched): `runtime/mail-watcher.log` 329 MB.

## 5. Suite runs and base comparison (M-011)

- Full suite from the worktree, environment inherited from this seat (45
  `AGENTSTACK_*`/`AGENT_NAME`/`PROJECT_KEY` variables present):
  `PYTHONPATH=. .venv/bin/python -m pytest -q` → **34 failed, 1573 passed,
  32 skipped**, 663 s, exit 1 (`full_pytest_run1_worktree_env-inherited.txt`).
- Of the 34: 2 were caused by this branch and are fixed —
  `test_runtime_contract.py::test_actual_tool_schemas_match_the_frozen_live_contract`
  (fixture, §1) and
  `test_stat_portability.py::test_no_shell_script_tries_bsd_stat_before_gnu_stat`
  (§4).
- The other 32 live in 9 installer/dashboard-service files. Same 9 files,
  scrubbed env (`env -i HOME PATH TMPDIR`), isolated fixtures only, no live
  installer: pristine `git archive e5039ff` tree → **14 failed / 109
  passed**; this worktree → **13 failed / 110 passed**; the worktree's
  failing set is a subset of the base's (the one extra base failure,
  `test_runtime_defaults.py::test_runtime_code_has_no_legacy_claude_fallback`,
  passed in the worktree run — reason not identified). What this shows is
  limited to those 13 tests under that one environment: it is **not** a
  proof that all 32 env-inherited full-suite failures reproduce at the base
  under identical conditions; the classification of the remaining ones is
  open (parent 8443: out of this station's scope). Outputs:
  `installer_files_base_e5039ff_scrubbed-env.txt`,
  `installer_files_worktree_scrubbed-env.txt`.
- Focused impact run after all review fixes (`packages/agentstack_mail/tests`
  + `tests/test_docs_consistency.py` + rotation/stat/bash32 tests):
  **761 passed, 26 skipped, 1 error**, 265 s, exit 1
  (`focused_impact_run_worktree.txt`). The error is the session-level
  service watcher in `tests/conftest.py` (teardown of the last test): a
  listener on port 8765 present at session start stopped "while running
  <none>" (between tests). No test in this branch touches port 8765 or
  18765 (the reply tests use an in-process client, the rotation tests temp
  dirs); the live ORRERY Mail (pids 7517/7519 on 18765, etime 4d21h) is the
  same process as at station start. What was on 8765 is not identified.
  Observed leftovers of the isolated installer tests (base and worktree
  runs): four orphaned `agentstack-mail-service foreground` processes from
  this worktree's `.venv`, each under a pytest tmp home
  (`pytest-23/25/28/29`), ppid 1, listening on ephemeral ports 60969, 64491,
  61558, 63055 — reported to the parent first (kill was outside the
  station's boundary), then torn down under the parent's explicit
  authorisation (mail 8465, limited to those four fixture trees):
  - Re-verification 2026-09-19T15:40:11Z, per pid: wrapper
    `/bin/bash …/pytest-{23,25,28,29}/test_noninteractive_assume_yes0/home/
    .agentstack/mail-service/renders/<render>/run-agentstack-mail.sh`
    (ppid 1) → `…/orrery-telemetry-wt-g1-reply-ack/.venv/bin/
    agentstack-mail-service foreground` → `…/.venv/bin/agentstack-mail`
    listening on 127.0.0.1:60969 / 64491 / 61558 / 63055. Live ORRERY Mail
    re-checked at the same time: pids 7517/7519, `lsof -iTCP:18765` → 7519,
    a different process tree.
  - 15:40:27Z `kill -TERM` to the four `agentstack-mail-service` pids
    (25603, 36798, 60021, 93286) one by one; after 3 s all four and their
    `agentstack-mail` children (25615, 36820, 60030, 93316) had exited and
    `lsof` on the four ephemeral ports returned nothing. The wrapper bash
    loops (25600, 36791, 60014, 93283; their script file already deleted
    with the tmp home, each sitting in `sleep 5`) were still alive and
    would respawn, so after re-checking argv (same tmp homes) and ppid 1
    they received `kill -TERM` at 15:40:59Z; after 7 s all four and their
    `sleep` children had exited. No `pkill`, no pattern kill, no service
    operation. Live mail afterwards: 7517/7519 unchanged, 18765 still
    served by 7519.
  - Residual, **not touched** (outside the authorised set): pid 82304,
    system python running
    `…/pytest-22/test_launchd_in_place_upgrade_0/old-dashboard.py`
    (started 00:09 JST during the first full-suite run, listening on
    127.0.0.1:58662, ppid 1) — a leftover of the base-origin
    `test_dashboard_service.py` failure; reported for a separate decision.

## 6. Limits

- Cross-project reply branch: source-checked, not end to end (§1).
- Route per row cannot be read from the DB; the audit log covers 09-09 →
  09-15 03:03 JST only; builds other than the single present candidate are
  unverified (§2).
- Watcher rate: one 60 s window at 23:57 JST with 906 pending files; the
  gap to the theoretical 1,812/min is unexplained; the proposed diff was not
  executed anywhere (§3).
- Rotation has not touched any real log; intraday overshoot and the
  copytruncate window are stated, not fixed; a leftover lock now needs a
  human (§4).
