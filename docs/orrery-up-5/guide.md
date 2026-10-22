# ORRERY-UP-5: Codex background-terminal work display

台帳: R-005・R-102・M-011・M-018・M-020・M-039・R-095。

UP-4 (`bac66a3a9632a7f9c6b1ff1c7cd0d246e51a7423`) の上で、Codex の
`esc to interrupt)` の後の ` · N background terminal(s) running` とその後の
補助表示を work と判定する。経過尺の解析は従来のまま（時・分・秒に対応）。
過去の作業行より現在の入力・承認・hooks の画面を優先する規則は変えない。

## head が導入するとき

31 の後、head の対話端末で、fork の新しい ref から入口を取り出して実行する。
下の `REVIEWED_ENTRY` は head が保存・レビューした入口の絶対 path。
共有 checkout の branch は切り替えない。

```bash
git -C /Users/huyuhutaru/tools/orrery-telemetry fetch fork mellowturing/orrery-up-5-codex-background
# 内容をレビューし、head の記録 root の REVIEWED_ENTRY に保存する:
git -C /Users/huyuhutaru/tools/orrery-telemetry show fork/mellowturing/orrery-up-5-codex-background:scripts/run-mail-fetch-upgrade-from-ref.sh
/bin/bash "$REVIEWED_ENTRY"
```

入口は UP-4 のものから以下を交換済み。

- ref: `fork/mellowturing/orrery-up-5-codex-background`
- governor task: `ORRERY-UP-5-owner`
- reuse-key: `orrery-up-5-owner-source`
- owner branch: `upgrade/orrery-up-5-owner-20261023`
- accepted-evidence: `docs/orrery-up-5/guide.md`

入口は `AGENTSTACK_FLEET_COMPAT=1` で `scripts/install.sh --mail update` を
対話実行する。既存の確認は head が応答し、`--assume-yes` は使わない。
この修正駅では live への導入・再起動を行わない。

## 試験

`tests/test_dashboard_runtime_activity.py` に実 pane fixture、時分秒と suffix の
組合せ、会話本文の陰性対照、終了行の後は wait の対照を追加する。
`tests/test_dashboard_runtime_cache.py` の既存承認 modal・hooks・旧 work/wait と、
UP-4 の実 fixture 2 本も回帰対象。UI の撮影・live の表示は本駅では未測定。
