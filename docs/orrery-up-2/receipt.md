# ORRERY-UP-2 受領書

準備版の検証は完了。本物の `~/.agentstack` へのinstallは未実施で、殿の端末で対話実行する（R-005）。最終のremote SHAと作業copy撤去後のdfは、同じ内容を残すrecords内の本受領書と `remote-proof.json`・`cleanup-final.json` に追記する。

基準は本家tag `2026.10.22` / `15c00c54c9774c390bdafe332603292b506d76d2`。forkの新branchは `upgrade/orrery-up-2-20261022`。試験したpayload commitは `711878cc15bbbb83e60a01aa654cb3d52cc61cf2`。UP1 `29070a0d6bbab0d0db6227a783f0f9b8b30eb5ae` と元fork `e5039ff` の祖先関係も保持した。

旧inventory307行のうち、比較した297件は同一277・変更20・削除0。bytecode・Mail service render・merge結果の生成物10件は未測定のままinstaller範囲外で保持する。新規68件（UP1の別表に既出のenv履歴4件を含む）を足して375行。UP1のmigration-mapは316データ行すべてを元行hash・新対応へ結んだ。保留は0。採録した原コード78 fileのhash不一致は0。

現行の世代releaseは5 regular file・3 symlink、計8件を保存した。head便35265に従い既定はcompatibility dispatcherで現行世代を使う。本家coreは `.upstream` の別pathに保持し、API26 dashboardには世代所有権callbackだけを移した。restart-seat・spawn-codex・spawn_childの3入口は、旧側のbin/hooks依存まで現行hashで凍結して対照し、token/state名・0600・pane名とmode・生存が一致した。providerとMail登録はsynthetic、tmuxは実process。実Claude/Codexの有料稼働・本番全席の再起動は未測定。

全repo試験は `7771 passed, 120 skipped, 1961 warnings, 169 subtests passed`、failed/error 0、exit 0。優先度2の既存heavy wrapperと終了watcherの中で、省略しないdurable logを取った。途中の赤と実行条件の誤りも残し、本家でも赤という理由で合格にしていない。本家tag単体の対照は16 failed・587 passed・6 skipped、exit1だった。sourceはtagそのもので、追加したのはprocess停止拒否fixtureだけ。

実installerの最終試しは、隔離HOME・`--install-dir`・`--scoped`・専用port、`--assume-yes`なし。installer/wrapper exit0、358件seed・323件比較の不一致0。native-TLS bin/注記2行/install-state・sandboxと独自exportを保持。Mail health ready、dashboardはversion2026.10.22/API26。終了後はMail50347・dashboard50348の両port閉鎖を確認した。pkill/killallを隔離PATHの拒否stubにし、startupの `pkill refused` を実記録した。doctorは12件の警告でexit1（下記原文）。Linux service managerとtmux検出をstubにし、scopedで人の設定承認を行わない試験なので、本番install成功や通知常駐の証明にはしない。

付属の単独restore toolも実snapshotで試した。353記録を戻してexit0、変更したpayloadのSHAが旧値へ一致。隔離DBのSHAとruntimeの目印は変わらず、新規core alternateも残った。試験で残った隔離Mail2本・専用pane・watcherもPID/専用socket/portの所有を確認して停止し、owned rootのhelperは0。本物のMail18765はPID64127でLISTENを確認し、DBを開く操作や停止は行っていない。

Mailはwrapperが `--mail keep` を明示するので、今回DB移行は不要、payloadの巻戻しが可能。本家legacy db.pyは前回tag以後差分0。稼働candidate 5e43de6との差は `credential_generation INTEGER NOT NULL DEFAULT 0` の追加DDL1行。Mail build更新時の実DB適用と旧build復帰は未測定なので別作業にする。namespace/globalの移行は明示opt-inで、candidateへ新規書込み後はrollbackを拒否する設計。今回それを有効化しない。

本家coreの失敗cleanup/資格削除、早期終了検知、resume/unretire、lock/lease回復は後続4項目として明記した。UP1準備版のformal-binding restartへの切替も現行世代の既定では有効にせず、head裁定の後続項目に含めた。追加更新は、先にpayloadの実端末確認、その後にMail buildとoptional Codex予約guardを別の対話作業で確認する提案。TLSの実ネットワーク安全性は本駅では未測定で、head便35273の根拠を引継ぐ。

upstream報告候補: 起動時のttyd cleanupが、同一機の別installのweb端末まで消す可能性がある。head便35280/35281に従い製品codeは本家のまま、issue/PRは作らない。初期試しの前後のttyd censusは未測定で、影響なしという15席・HTTP200の実測はhead便35280のもの。

## 殿の1本の手順

詳細はこのrecordsの `guide.md`。SpotlightからTerminal.appを開き、次の1行。上書き前に暗号化DevSSD-Privateへ旧payload・env・settings・managed documentsをhash付きで退避する。退避に失敗したらinstallerへ進まない。settings、Claude MCP、Codex AGENTS、Claude CLAUDEの4承認は、表示された対象と差分を読んで適用するならそれぞれ `yes`。終わったらinstaller/doctor exit、snapshot path、警告をheadへ報告する。

```sh
/bin/bash <(git -C /Users/huyuhutaru/tools/orrery-telemetry show fork/upgrade/orrery-up-2-20261022:scripts/run-fleet-upgrade-from-ref.sh)
```

戻すときは表示された絶対pathで `<SNAPSHOT>` を置換し、3行。

```sh
python3 '<SNAPSHOT>/restore-tool.py.txt' restore --home /Users/huyuhutaru --directory '<SNAPSHOT>'
/Users/huyuhutaru/.agentstack/dashboard/agentctl.sh restart
/Users/huyuhutaru/.agentstack/bin/agentstack-doctor
```

## 証拠

各行は、残すfileの絶対path・SHA-256・示す内容。sourceの作業copyはpush照合後に撤去し、コードはfork refから復元する。

| file | SHA-256 | 何を示すか |
|---|---|---|
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/identity.json` | `6b35cabb42f6e16216e9d67dc71ce70ccee28bfb7d0467c1a250ef9adb27e4a9` | 基準tag・723 commit・共有checkout・試験payload SHAと裁定便 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/ancestry.json` | `2eb9db13f3b2457c562e909a19e24e9b1c88eaef0fc338b8cccd3caeb3e6d1b8` | 本家tag・UP1・元forkの三つが祖先である |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/inventory.json` | `c90b9c52e08f083b0a1c93786ee71a9c27000280dc94b0c374012c72c77e1790` | 旧307行と新規68行の対応、SHA、移植commit・保存先 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/inventory-audit.json` | `ea5f5962782067e48abc52c3456274d71ea7a53da6e9563577e401b3ab4d6fe3` | 351 code pathの探索で未採録0・消失0・採録後変化0。生成物10件は比較外 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/up1-row-map.json` | `e8c5739eb916df7402cdb77069ce65fe5220d13742dca54e047dbc5a03e2940d` | UP1 migration-mapの316データ行を元行hash付きで全件対応 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/migration-map.md` | `4d3a858f15c7f31cfe179ec4cb29576450682b294b8f1b51b3ebe7b2876d5fe4` | 全375行と外部git設定の扱い、本家同等error表示の引用 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/source-preservation-audit.json` | `0471e62727e3fbacddeae7742e37f527cda52e4d88eac6a4edad887d36c2817d` | 採録した78 fileの原bytes hash一致、実行sourceに未解決marker0 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/full-suite-third.log` | `58924401f31f1e3320c74192f9c3eae2715eceddcc055789a5d8fa12a683d82c` | 全repo試験7771 passed・120 skipped・169 subtests passed、exit0 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/verification-runs.json` | `a2ae80de0c0bf904bad8c095fb4d9605bf664b593600f62b7aab1b3b2972761e` | 省略なしの各試験logとexit、途中の失敗・中断も記録 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/test-history.json` | `3753ae5c9690e0cf4637ff8ac86048fd3126faf6834879cd139d0329be4ae577` | 赤118識別子の発生条件/持込commit・assertionの意味・修正・本家対照 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/upstream-control-identity.json` | `de7fe4f37dd4f85246a1d0d4595bc4a5bc54d471a2eedb195d5b74681a5b2345` | 本家対照の製品sourceはtagと一致。差は停止拒否fixtureだけ |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/upstream-red-controls-git.log` | `ac63728434e4e607871f9fc4ef8ebe88ac8a8cb925e78efffa002c07adff542a` | 本家tag対照は16 failed・587 passed・6 skipped、exit1。合格の根拠に使わない |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/parity-restart-seat.json` | `022f795d7c8991241ee5c8b2e78ef979831ffb0ec62a6be7f95ff16ecac26719` | 現行bin/hooks依存を含む旧側と新側のtoken/state名・0600・pane名/modeが一致 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/parity-spawn-codex.json` | `022f795d7c8991241ee5c8b2e78ef979831ffb0ec62a6be7f95ff16ecac26719` | spawn-codex入口でも旧新の同一性とTLS変数除去を確認 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/parity-spawn_child.json` | `022f795d7c8991241ee5c8b2e78ef979831ffb0ec62a6be7f95ff16ecac26719` | spawn_child入口でも旧新の同一性とTLS変数除去を確認 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/rehearsal.json` | `6b726d79cc13bad7f21bad816d15e399abc5ff594d6d5d2a606a126b4a492a2e` | 実installer exit0、比較323件の不一致0、MailとAPI26 dashboardが立ち、両port閉鎖 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/rehearsal-final-audited.log` | `5ca27f93461f17422ceefd978565884159603cec4ceed359188efb2d6e3c72bf` | --assume-yesなし、隔離HOME/install-dir/scopedの全installer出力。doctor exit1 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/process-cleanup-refusals.txt` | `125f7d21ae8567d6a213f6f715244974f149569a0877a255627ee6f005941153` | dashboard startupのpkillは拒否stubに到達 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/rollback-proof.json` | `a8185688f25b258bbe98b30ebe13c9a1451b9158ded161e3d7cf2923ab4236ee` | 単独restore toolが353記録を戻し、payload hash一致・隔離DB不変・runtime目印保持 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/rollback-final.log` | `fd9e050909fd9e7d6914df329dc54a30aafd59ee35eac48908582daa8f80833b` | 実snapshotからのstandalone restoreの全出力とexit0 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/upstream-range.json` | `49a9c7cdc68eae8c8c0bcee86c57689e6dd282fe1d160c23be94775378e7ebba` | 09.30.4以後のlegacy db.py差分0、5e43de6以後の追加DDL1行 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/upstream-changes.md` | `56e4176f51f3b2aaa5dcd9bd0651156f19f21cc2966d1a179e69e0be78149c11` | 本家の運用変更10項目・後続4項目・追加更新の提案 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/external-config.json` | `60f8227cd732571aac44ddec24133dbfb3635052339c82bcf50ebf16ed8c1c70` | native-TLS wrapperとgit http.sslCAInfoを保持、外部設定を本駅が変えていない |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/safety-audit.json` | `9b2ef1ae13bd0f375530b49c65fdd512c19b2af4148e682e2e0854f9d001dd8c` | 既存pkillの発見・head裁定・最終stub測定を区別 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/process-cleanup.json` | `9e72f0af3fd5effe3107219e6e3857d13ce2b3406a89ff07dee746ef23a8215a` | 残った隔離Mail2本と専用pane/watcherだけを停止 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/process-audit-final.json` | `117222682e3a2850e5bcb535d5bcd1a09c4c11736b877337400789e3335a4772` | owned rootに依存するhelper processは0、実Mail18765のPIDを別記 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/upstream-control-bundle.json` | `1c13fe0e6997b9c9624975f6728b082ac9d943b1c3719f740e7f6385c90c4ad0` | 未pushの対照commitをR-095どおりbundleで退避しverify0 |
| `/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T084947Z-receipt-1639da14/guide.md` | `79a55265d2330320ee07349f6eeebbf7ff463a265a58aef51a491304c5b5c540` | 殿の端末の開き方・1行・承認4件・報告文・戻し方3行 |

## 隔離doctorの警告（原文）

```text
warning: AGENTSTACK_WORKTREE_ROOT: directory does not exist yet: /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/worktrees
warning: could not register the ORRERY Mail autostart unit; mail will NOT restart after a reboot. Start it manually with: /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/bin/agentstack-mailctl start
warning: could not register the ORRERY Mail watcher unit; agents spawned from the dashboard will not receive Mail notifications until an agent started with /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/bin/agent-start brings the watcher up
  warn: Codex AGENTS.md managed block in /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.codex/AGENTS.md; block hash unknown; managed block not found in /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.codex/AGENTS.md; add it with: env AGENTSTACK_HOME=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack CODEX_HOME=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.codex AGENTSTACK_PROJECT_KEY=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/project /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/bin/agentstack-codex-setup
  warn: Claude CLAUDE.md managed block in /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude/CLAUDE.md; block hash unknown; managed block not found in /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude/CLAUDE.md; add it with: env AGENTSTACK_HOME=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack CLAUDE_CONFIG_DIR=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude AGENTSTACK_PROJECT_KEY=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/project /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/bin/agentstack-claude-setup
warn: Claude MCP orrery-mail is not registered for http://127.0.0.1:50347/mcp in /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude.json
      /delegate cannot use ORRERY Mail until this fixed-name entry exists.
      preview: /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/source/.venv/bin/python /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/bin/agentstack-merge-claude-mcp --dry-run --config /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude.json --mcp-url http://127.0.0.1:50347/mcp --mail-env /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/mail-service/renders/711878cc15bbbb83e60a01aa654cb3d52cc61cf2-e91a95dbe3f81aa99440/service.env --backup-dir /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/backups
      apply:   /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/source/.venv/bin/python /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/bin/agentstack-merge-claude-mcp --config /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude.json --mcp-url http://127.0.0.1:50347/mcp --mail-env /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/mail-service/renders/711878cc15bbbb83e60a01aa654cb3d52cc61cf2-e91a95dbe3f81aa99440/service.env --backup-dir /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/backups --existing-result /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/runtime/claude-mcp-merge-result.json
warn: Claude Code's first-run setup is not finished (/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude.json has no hasCompletedOnboarding)
      Children launched now stop on its setup screens. Run 'claude' once in a terminal and go
      through text style, login, Security notes and trusting the folder until the normal
      input prompt appears; answer any other one-time question it asks, then /exit.
warn: mail watcher health is red (dashboard /api/mail-watcher-health: watcher_running=0, signals=0, actionable=0, orphan=0)
      mail delivered to an agent waiting for input may not wake it; see docs/troubleshooting*.md (mail watcher)
warn: Codex apply_patch reservation guard is not installed; edits may be unguarded. Install the optional plugin and review /hooks.
warn: Codex AGENTS.md managed block in /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.codex/AGENTS.md; block hash unknown; managed block not found in /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.codex/AGENTS.md; add it with: env AGENTSTACK_HOME=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack CODEX_HOME=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.codex AGENTSTACK_PROJECT_KEY=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/project /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/bin/agentstack-codex-setup
warn: Claude CLAUDE.md managed block in /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude/CLAUDE.md; block hash unknown; managed block not found in /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude/CLAUDE.md; add it with: env AGENTSTACK_HOME=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack CLAUDE_CONFIG_DIR=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.claude AGENTSTACK_PROJECT_KEY=/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/project /Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade/rehearsal/rehearsal-home/.agentstack/bin/agentstack-claude-setup
warn: no managed agent records found for scientist suffix check
```

## 片づけ

R-095/storage v6.0（2026-10-19）。最終削除のpath・bytes・file数・理由とdfはrecordsの `cleanup-final.json`。既存原本・他駅root・旧UP1 worktreeは触らない。未pushの本家対照commitはverify0のbundleで保存し、記録以外の隔離HOME・venv・試験生成物・git copyを撤去する。最終の実測値はrecords版の末尾に追記する。
