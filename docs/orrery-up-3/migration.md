# MAIL-FETCH-1 移植表

台帳: R-005・R-102・M-011・M-018・M-020・M-073・R-026・R-095。
基準 `ade977f8`、元 `fb17fa82a6473dbfe0ffaa78303464a0078ede0a` → `05f280e`、元 `77ff2e9e78f3fd2043f650f3172a4e893dc8a78c` → `5954f12`。

本家 tag `2026.10.22` には Mail `message_id` も Codex client の exact 取得もない。`ade977f8` 側に既にある同等機能は、本家で実装済みとして扱わず、fork の既存移植（主に `1d42c72`）として保持した。`port-map.json` は元 21 path の base / original / ported blob ID と実 diff を示す。

| path | 移植・衝突解消の意図 | 最終 diff の要点 |
|---|---|---|
| `bin/agentstack-await-reply`（衝突） | 現行 runtime client の fence・`--from-id`・cancel 対応 wait を維持。元の古い polling loop は採らない | `_pick` に optional exact ID の検査だけ追加。現行 CLI は既に exact ID を fetch に渡し行を絞る（base L236–245） |
| `docs/hooks.md` | 元の案内を移植 | 通知の message ID・本文分割取得・retained composer の再試行を記載 |
| `hooks/spawn_child.sh`（衝突） | 現行の起動時限定 skip・preview 読取・R-061・ORRERY SendMessage 指定を保持 | 最終差分 0。base `build_embedded_task_prompt` L2851–2862 に元の要求を包含 |
| `hooks/watch_agent_mail_signals.sh`（衝突） | 元の retained composer 検査は既存。所有者付き pane lease、head 除外、headless、mail-disabled を保持 | 古い無条件再送の保険 14 行だけ除去。base `inject_notification` L560–589 と `deliver_worker` L600以降を維持 |
| `integrations/codex_app/src/agentstack_codex_app/agent_mail_client.py` | exact schema discovery は既存 fork 移植を採用 | 差分 0。base L200–227 の optional `message_id` と非対応 server の fail-closed 検査 |
| `integrations/codex_app/src/agentstack_codex_app/mcp_server.py` | proxy の validation・本文 chunking は既存 fork 移植を採用 | 差分 0。base L209–271、schema L894–913 |
| `integrations/codex_app/tests/test_exact_mail_body.py` | 元の試験を移植 | 古い exact便、chunk 再構成、非宛先、非対応 server など |
| `packages/agentstack_mail/fixtures/tool-schema-extensions-v1.json` | 凍結 fixture を改変せず optional API を追加 | `fetch_inbox.inputSchema.properties.message_id` の version 1 拡張 |
| `packages/agentstack_mail/src/agentstack_mail/app.py` | 元の Mail 本体を移植 | optional positive integer `message_id`、recipient join を残したまま SQL に `Message.id` 条件。DB schema 変更なし |
| `packages/agentstack_mail/tests/test_pending_decision_d11_d12.py`（衝突） | 現行の並行 delivery/lease/headless に関する assertion を保持 | 元の helper 関数抽出（subshell対応）と、submit 後 composer 検査が success 前にある assertion を移植。command 最終行は現行の安全な抽出を維持 |
| `packages/agentstack_mail/tests/test_runtime_contract.py` | 元の schema 拡張試験を移植 | 元の全 schema fields と現行 `existing_agent_id` optional recovery guard の双方を維持 |
| `tests/test_await_reply.py` | 元の試験を移植 | oldest match と exact old ID の独立性、明示 error を確認 |
| `tests/test_notification_submission.py` | 元の試験を移植 | retained draft の Enter 再送、持続失敗、別通知の入力中は defer |
| `tests/test_spawn_child_embed_task.py`（衝突） | 現行の argv 注入・owner contract を保持 | 起動時だけ skip、preview 後 fetch の assertion 2 行追加 |
| `CONTRIBUTING.md` | 元の環境説明を移植 | 収集前の HOME・launcher env 隔離を明記 |
| `conftest.py` | 元の isolation を移植 | collection 前に launcher env を除去し fixture HOME を設定。実 HOME/資格を試験へ持ち込まない |
| `packages/agentstack_mail/pyproject.toml` | 元の互換 pin を移植 | `sqlmodel==0.0.42`。SQLModel 0.0.48 の naive UTC 拒否を避け既存 model のまま検証。uvicorn/Pydantic の現行 pin は保持 |
| `scripts/install-state.sample.json`（衝突） | 現行 fixture の explicit codex path・追加 env を保持 | 差分 0。元の `__CODEX_BIN__` 正規化は現行 fixture と合わないため採らない |
| `tests/test_codex_launch.py`（衝突） | 現行の共通 readiness helper に対する assertion を保持 | 元の portable `python3` と codex 探索 fixture を移植。古い文字列出現数による assertion は採らない |
| `tests/test_register_tokenless.py` | 元の portable fixture を移植 | 明示 fake Codex binary と provider 設定。実機上の executable 探索に依存しない |
| `tests/test_runtime_defaults.py`（衝突） | 現行 explicit `codex_bin`・retention・child overlay・enroll normalization を保持 | fake bin に Codex stub を追加。元の重複 CODEX_BIN と placeholder normalization は採らない |

新規 `scripts/verify-exact-mail.py` は、本物の DB を引数で受けず、model schema の合成 seed を自分で作り SQLite backup した copy だけを HTTP server に渡す。1 通の本文一致、2001 年の便の exact 取得、非宛先 0 件、recent filter 0 件、seed 不変、終了後 port 閉鎖を検査する。初回は seed 初期化で models import を欠き、製品 server 起動前に失敗したため import を追加した。

新規 `scripts/run-mail-fetch-upgrade-from-ref.sh` は head 専用の未実行入口。UP2 の `--mail keep` 固定 wrapper を変更せず、`--mail update` を明示する。確認対象と未測定範囲は `guide.md` を参照。

README・AGENTS・Claude/Codex の managed 指示・install/hook docs を確認した。起動/承認の製品フローは変わらず、既存 `docs/hooks.md` の exact 取得案内と本表・guide で補う。配布の新規設定項目は増やしていない。
