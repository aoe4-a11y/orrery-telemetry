# ORRERY-UP-1 受領書

準備branch `upgrade/orrery-up-1-20261001` を fork `aoe4-a11y/orrery-telemetry` へ pushした。隔離installのcode commitは `fb2cd26f9cdffe1666c440114f8b2c69fc4fe987`。最終試験の対象は `36bf85a4ca054ec3a62736b526eeeb72cbc6fe10` で、差分はtest2fileのみ、install payloadの変更は0件。本家の最新tag確認値は `2026.09.30.4` (`27b9fb1b46bb24d28f1d6fdb3270b6d31bb5334a`)。forkだけの4 commitはmerge ancestryで保持している。最終全体pytestは3204 passed / 33 skipped / 17 subtests passed、exit0で完了した。

## 改造と履歴

`inventory.json` と `migration-map.md` は全307行を列挙する。owned252件はstack内247件＋外部link/service5件。同名差分7件、同名sourceなし55件（owned backup4件も含めると59件）。追加payload28件、code/config backup37件、env backup4件を採録した。286件の現行code/config/backup/env履歴を再hashし、採録後drift0だった。runtime credential/token/実Mail DBは読取り対象にしない。ownedに含まれた生成runtime metadataはpath/hashだけを採録し、内容をrepo/mailへ出していない。

各fileを移植commitへ対応付け、旧世代のbytesはbackup-generationsへ保存した。現行supervisorなどの累積改造はactive codeとしてinstall対象へ移した。旧optional server-error表示だけは、本家 `_safe_error_text` の600字制限・secret redactionが同じ目的を実装しているためそちらを採用した。該当本家行・引用は対応表にある。

Codex既定を `gpt-6.1-sol` にし、restart-seat、spawn-codex例示、spawn model resolverへ反映した。実CLI0.159.3でresolverと既定effort mediumを隔離runtimeで実走し、3 commandすべてexit0。課金を伴う `codex exec` は再実行せず、headが確認済みの結果を利用した。R062未承認のadvanced effortをproviderのメニュー用payload・cache・resumeの設定生成で避け、明示許可時のcapabilityは保持する。

## 使い捨てinstall

本物installerを隔離HOME・`--install-dir`・`--scoped`で実行した。`--assume-yes` は使用していない。隔離native Mailと実DB・dashboardを別portで起動し、installer exit0、Mail ready、DB path一致、VERSION一致、custom env exports保持を確認した。Mail port53235、dashboard53236。試験を始めたhelperは停止確認済み。

71 comparisonのうち現行liveとraw byte一致65件、移植branch期待値と一致71件（active34件＋backup37件）、不一致0。`live-to-install.diff` が6件の本家更新・意図したモデル等の変更を示す。config R068とbackup世代はbytes一致。追加照合で本家safe-error/core inbox実装・Codex resolver・child resumeの4 sourceはbranchのbytes一致、optional integration metadata3件はcore installerの既存policyに従い現在のbytesを保持した。optional integrationの再installは未実施・未測定（`installed-latest-source.json`）。

service manager/tmuxは本家repoの試験手法に従い隔離Linux stubを使用した。8件のwarning全文を `rehearsal-warnings.txt` に保存した。未作成のworktree/add-dir4件、autostart/watcher registration2件、`--scoped`で承認対象のmanaged blockを追加しなかった2件である。macOS launchd、所有者の対話承認、実fleetのrestart、実Mail package upgrade、実端末rollbackは未測定。

## 全テスト

最終実行はcanonical heavy wrapper内で `PYTHONPATH=. .venv/bin/python -m pytest -q`。出力をpipeで絞らずdurable logへそのまま保存し、独立watcherがjob終了とexitを記録する。修正2件focusedは2passed、exit0（11.88s）。最終全体は3204passed / 33skipped / 17subtests、7warnings、exit0（1136.42s）。warningはAuthlib2件・multi-threaded fork1件・streamable HTTP4件で、全文をlogに保存した。

初回全体は `2b2ac5e` でexit1（24failed/3179passed/33skipped）。2回目は `fb2cd26` でexit1（2failed/3202passed/33skipped）。残った2件はa931cc3のowner config保持・9cccf55のR062未承認effort menuをassertionへ反映し、36bf85aでexact config bytesと未承認3 effortを明示して修正した。失敗test名、assertionが要求する動作、policy移植のintroducing commitと修正を `test-history.json` に列挙した。process起動/merge timeoutの導入時点は未特定と明記し、baseline redとして免除していない。最終全体で赤0を確認した。初回timeoutの導入commit/原因は未特定のまま明記し、通ったことから原因を推定していない。

## 所有者のinstallとrollback

殿の端末で打つ1本:

```sh
/Users/huyuhutaru/tools/orrery-telemetry-wt-orrery-up-1/scripts/install-fleet-upgrade.sh
```

wrapperは暗号化DevSSD-Privateへ旧payload/config/settings/doc/serviceをhash付きで保存し、その後installerを対話実行する。保存先は端末に `Rollback snapshot:` と表示される。[手順とrollback](guide.md) の3 commandで旧bytesを戻してdashboardをrestartしdoctorを実行する。restoreはsnapshotの全SHA確認後に実行し、Mail/DB/runtimeを巻き戻さず新規追加fileも削除しない。隔離実install先で310 recordのsnapshot/restoreを実走して両command exit0、変更したrestart-seatの元SHAへの復元とruntime sentinel保持を確認した（`rollback-proof.json`）。

このstationは本物 `~/.agentstack` にinstall/書換えをしていない。共有checkoutは `fix/claude-prompt-nbsp` @ `e5039ff79663d99764d83e0cfa6961074ec60199` のままclean。稼働Mailを止めず実DB/tokenを読まず、fork既存branchへのforce-pushと本家pushをしていない。device/Simulator試験・作成は0件。

## 証拠

証拠一覧は以下に固定する。送信時の最終delivery SHAはparent便およびdelivery-proof.jsonに記載する（受領書自身のcommitを自己参照させないためpost-push記録）。

## 隔離installerのwarning原文

```text
warning: AGENTSTACK_WORKTREE_ROOT: directory does not exist yet: /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.agentstack/worktrees
warning: AGENTSTACK_CODEX_ADD_DIRS: directory does not exist yet: /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/Library/Application Support/DevStorageGovernor
warning: AGENTSTACK_CODEX_ADD_DIRS: directory does not exist yet: /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.dev-storage-governor
warning: AGENTSTACK_CODEX_ADD_DIRS: directory does not exist yet: /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/Documents/Codex
warning: could not register the ORRERY Mail autostart unit; mail will NOT restart after a reboot. Start it manually with: /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.agentstack/bin/agentstack-mailctl start
warning: could not register the ORRERY Mail watcher unit; agents spawned from the dashboard will not receive Mail notifications until an agent started with /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.agentstack/bin/agent-start brings the watcher up
  warn: Codex AGENTS.md managed block not found in /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.codex/AGENTS.md; add it with: AGENTSTACK_HOME=/Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.agentstack CODEX_HOME=/Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.codex AGENTSTACK_PROJECT_KEY=/Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/project /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.agentstack/bin/agentstack-codex-setup
  warn: Claude CLAUDE.md managed block not found in /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/project/CLAUDE.md; add it with: AGENTSTACK_HOME=/Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.agentstack AGENTSTACK_CLAUDE_MD_SCOPE=project AGENTSTACK_PROJECT_KEY=/Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/project /Volumes/DevSSD/DevStorageGovernor/artifacts/orrery-telemetry/20261001T011558Z-build-cache-33928e51/rehearsal-home/.agentstack/bin/agentstack-claude-setup
```

## 証拠一覧（SHA-256）

| path | SHA-256 | 実際に示すもの |
|---|---|---|
| `docs/orrery-up-1/identity.json` | `0fdb28c75dd75e29f2e72bb65e3499acc6ce03c8b973b271db8078adc5029069` | 本家tag・fork4commit・隔離installと最終testのcommitを固定 |
| `docs/orrery-up-1/inventory.json` | `79151bb533c5720b602569f6e65acdfbfd133350181c3586d1eb0e5a82341cd0` | owned252・追加/backupを含む全307行のpath/SHA/移植先 |
| `docs/orrery-up-1/migration-map.md` | `bf935c1a61d217440dcbb608d5cd0d61bbccfc2621aef20333e83de27f9478ca` | 各改造と移植commit、55件source不在、backup世代、upstream同等箇所の対応 |
| `docs/orrery-up-1/final-census.json` | `2850b551e7a96ba0f973a6a7f4133bce2f99434e87302569c56612172621e0cd` | owned7差分・55source不在＋4owned backup・外部owned5の件数 |
| `docs/orrery-up-1/coverage-final.json` | `f1bba97662a7583edd4fbfc68e3c39999fb0aaf446eb3bcaad1e5a81eb70b078` | bin/hooks/config等8領域288regular fileの未採録0 |
| `docs/orrery-up-1/final-destination-check.json` | `4a086329139c5f51a78439896ef2e89c0b5507d1fd1cce96752fe60c3b4ccb78` | 現行code/config/backup286hashのdrift0、祖先5件、canonical checkout未変更 |
| `docs/orrery-up-1/live-to-branch.diff` | `9a2b2a6341dcdc51918f0ce655aed577d1dc156b108e2faeb7fd86ea4e11350c` | 現行コードと移植branchの差分全文 |
| `docs/orrery-up-1/live-to-install.json` | `46575ee31c09ac7e4c05101980700c6d70b0bf7c2d678cd725475f11f4146828` | 71対象でraw65一致・移植branch71一致 |
| `docs/orrery-up-1/live-to-install.diff` | `e93af0ca2b9786b27c8c8d0515a7cfe3cbd6feddb55785289a52010a69d9c257` | 現行と使い捨てinstallの6差分全文 |
| `docs/orrery-up-1/installed-latest-source.json` | `8efc70973c0a64b721abf00e639f2d7f279f67668e8e5c6d80addceb94555447` | core4sourceを最新branchで置換しoptional metadata3件は現行値保持 |
| `docs/orrery-up-1/rehearsal.json` | `0f4cfb57db28603f1d9b29aac047f49030b84431d0807439e628e736003c974d` | 実installer exit0・隔離Mail/DB/dashboard正常・71comparison・teardown |
| `docs/orrery-up-1/rehearsal-second.log` | `c7995c5e80456574e8267de86225945e097e04eea4357a3ea47a68e376f7b2b3` | 使い捨て実installerの出力全文とexit0 |
| `docs/orrery-up-1/rehearsal-warnings.txt` | `f260d1315cc389a3c9773d28bfac6f04b9c6963eb22eb877e122909a9419daa0` | 隔離service stub/承認skipに由来する8warningの原文 |
| `docs/orrery-up-1/rollback-proof.json` | `d1eeb17eb12646c5185f75f1ee49e34b8f48e1fda81a59ed04f86f32628598fc` | 隔離先310recordのsnapshot/restore両exit0・元SHA復元・runtime保持 |
| `docs/orrery-up-1/model-default-proof.json` | `8017b9ce60d119accf6b08d90b17c9f4d3c6ad29af4ca8ff67c034ae9885f9dc` | 実Codex0.159.3のresolver gpt-6.1-sol・medium、3command exit0 |
| `docs/orrery-up-1/test-history.json` | `d1d45f60201f5e0e09a07a09f227f2b3c4d61fc28ea4c32830bbebf324741698` | 初回24赤と2回目2赤のassertion・導入変更・修正・未特定の範囲 |
| `docs/orrery-up-1/full-suite-first.log` | `d7ad64e478845a31d3acf10b1a52c9d8281f2327830229c00e0d6b4e78744ab6` | 初回全体24failed/3179passed/33skipped、exit1の出力全文 |
| `docs/orrery-up-1/full-suite-final.log` | `2041fe1c875657627e4f8707c7d9bb701d253252f460e07c86fe62f99af72e59` | 2回目全体2failed/3202passed/33skipped、exit1の出力全文 |
| `docs/orrery-up-1/last-two-focused.log` | `efaa49ceebc65f7920859cc5647e032569109226b8eb145c37ff9d5d794e07b6` | 残った2件の修正確認、単独pytest出力とexit |
| `docs/orrery-up-1/full-suite-verified.log` | `670426c099bdd8c579e38861263b5f62e4d3b8ee59e235fe498c24e830d74ba7` | 最終commitの全体pytest出力全文とexit |
| `docs/orrery-up-1/queue-route.json` | `7089758df961bc2f4564a01f592fb109a99293af6f6dc28cd4a80301e72f0714` | canonical heavy wrapperと21path探索、優先度実装0・上限変更なし |
| `docs/orrery-up-1/cleanup-check.json` | `b3063edcc19c4f4d7cdd1b9bd02a65a82ad2ea82a426901e11734affd66cbe42` | 隔離installのhelper process残存0・実service停止0 |
| `docs/orrery-up-1/guide.md` | `ec49122e2c9d3e5b927c05d5a0bbac6ff3854c96b13ed199be54c97e559519c1` | 所有者が実行するinstall1本とrollback3command・未測定範囲 |
| `docs/orrery-up-1/push-candidate.json` | `fed6a1c1f7760ea7307b5876b83a4cddaaa7987dce10911d7ab94ae6941f6c43` | forkへcandidate SHAをpushしremoteと一致させた記録 |
| `docs/orrery-up-1/log-credential-shape-scan.json` | `0da6b524a9e13d572ffa0f494d9ee6ec6fe8abb2ab94daa6240a50dcf79661e0` | station logの3種類のcredential shape検出件数（網羅性の限界付き） |
| `docs/orrery-up-1/optional-metadata-equivalence.json` | `a84c1a620ad56d32350770e1e0a8c49c668083c016d4a0195bde0a1ed985ec27` | owned metadataのschema titleとproject description以外は同一、制約/依存差分なし |
| `scripts/install-fleet-upgrade.sh` | `7420b9d51656505da6b1aeb63748ae3f528354b61bf51a979f6645e1277bbeeb` | 所有者用対話installer wrapper |
| `scripts/fleet-upgrade-backup.py` | `f4d4fb63ed86bde35649526c28862f49e8aa442d15deecb11e8cab371209f77f` | Mail/runtimeを除くsnapshot/restore実装 |
