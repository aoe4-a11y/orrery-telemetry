# ORRERY-UP-3 導入手順

台帳: R-005・R-102・M-011・M-018・M-020・M-073・R-026・R-095。
実行するのは head。席は本番へ導入しない。

fork ref を取得・照合した head の端末で、次の 1 行を実行する。

```sh
/bin/bash <(git -C /Users/huyuhutaru/tools/orrery-telemetry show fork/freshpauling/orrery-up-3-mail-fetch:scripts/run-mail-fetch-upgrade-from-ref.sh)
```

この入口は専用 governor root に sparse worktree を用意して `AGENTSTACK_FLEET_COMPAT=1 /bin/bash scripts/install.sh --project-key /Users/huyuhutaru/tools/examforge --mail update` を実行する。共有 checkout の branch は変えない。既存の `--mail keep` を固定した UP2 wrapper は呼ばない。

installer は候補の build、専用 port と DB snapshot による事前検証、DB backup の順に進み、成功後に本番を止めて切り替える。失敗時は旧版へ戻す。Mail 更新専用の yes 質問はない。`--mail update` 自体が切替要求で、auto の outage budget 制限は適用しない。接続断はあり得るので head が実行時刻を決める。本番の切替・復帰と実 DB に対する結果は、この駅では未測定。

確認は次の 4 件。head は表示された path と diff を読んで回答する。`--assume-yes` は付けない。

| 順 | 確認対象 | 実装 |
|---|---|---|
| 1 | `~/.claude/settings.json` への設定 merge | `scripts/install.sh`: `confirm_safe_merge` |
| 2 | `~/.claude.json` の固定 `orrery-mail` MCP 登録 | `scripts/install.sh`: `confirm_claude_mcp_merge` |
| 3 | Codex `AGENTS.md` の managed block | `bin/agentstack-codex-setup` → `bin/lib/instruction_blocks.py` |
| 4 | Claude `CLAUDE.md` の managed block | `bin/agentstack-claude-setup` → `bin/lib/instruction_blocks.py` |

最初の 2 件は `Type yes to continue`、後の 2 件は既知の既存 block があれば `Move known ORRERY instructions to the user file and remove old blocks? … [Y/n]`。後者の空回答は移動・除去への同意、`n` は既存 block を保持する選択。既に同一の項目や新規 target は確認が省略される場合がある。Mail の token・DB・登録は新しく作り直さない。完了時は installer exit、`mail-result:`、選択された candidate と service env の path、稼働 PID、exact fetch の再確認を head が記録する。`agentstack-doctor` の警告は原文を残す。source worktree の片づけ候補は入口が path・bytes・file 数を出力するので、稼働 Mail の candidate/venv と区別して処理する。

この wrapper 自体は本番未実行。shell 構文検査と repo 試験、隔離 Mail の HTTP 証拠を受領書で示す。
