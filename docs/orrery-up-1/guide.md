# ORRERY-UP-1 所有者の更新・rollback

台帳: R-005 / R-026 / R-061 / R-062 / R-068 / M-011 / M-018 / M-020。

本家 `2026.09.30.4` に fork の4 commitと現行fleet改造を載せた準備branch。実 `~/.agentstack` へのinstallは所有者が端末で対話実行する。stationはそこへinstallしない。

## installの1本

```sh
/Users/huyuhutaru/tools/orrery-telemetry-wt-orrery-up-1/scripts/install-fleet-upgrade.sh
```

このwrapperは暗号化DevSSD-Privateのgovernor archiveへ、上書き対象のpayload・env・settings・managed documentsを先に保存する。保存manifestのpathとSHAを表示し、その後に本家installerを `--assume-yes` なしで実行する。4種類のsettings/MCP/doc承認は端末で内容を見て回答する。現在のexplicit Codex候補に `gpt-6.1-sol` を足し、既定を使える状態にする。実行後のdoctorのwarnはそのまま表示する。

Mail・runtime・tokenはbackup/rollbackの対象にしない。installerは健康なMail listenerを再利用し、停止・DB移行を要求しない。Mail packageには `credential_generation` 列追加があるが、このstationでは実DBを開かず、既存listenerのpackageも置き換えない。稼働Mailのversion更新は未測定。

## rollback

wrapperが表示した `Rollback snapshot:` の絶対pathを次の `<SNAPSHOT>` に入れる。

```sh
python3 /Users/huyuhutaru/tools/orrery-telemetry-wt-orrery-up-1/scripts/fleet-upgrade-backup.py restore --home /Users/huyuhutaru --directory '<SNAPSHOT>'
/Users/huyuhutaru/.agentstack/dashboard/agentctl.sh restart
/Users/huyuhutaru/.agentstack/bin/agentstack-doctor
```

restoreは全snapshot fileのSHAを照合してから、旧payload・設定・managed document・記録したservice定義を戻す。Mail、DB、runtimeに蓄積した新しい記録は戻さない。新規追加されたfileは削除せず残るので、rollbackは旧対象のbytes復元であり、新規file全消去ではない。dashboard restartはdashboardだけを対象とする。変更したwatcherを現在のprocessへ読み直させる作業、実端末のrollbackは未測定。

## 検証範囲

- `scripts/rehearse-fleet-upgrade.py` は現在のcode-only snapshotとtoken-free envを隔離HOMEへseedし、`--install-dir` / `--scoped`で本物のinstallerを実行する。実Mail DB・dashboardを隔離portで起動する。
- service managerはrepoの試験方法に従ってno-service Linux stubとし、production launchd/tmuxに触れない。ユーザー承認・macOS launchd切替・稼働fleet全席restartは未測定。
- [全対応表](migration-map.md)、`inventory.json`、`live-to-branch.diff`、`rehearsal.json` と [受領書](receipt.md) が証拠。
- AGENTS.md / claude/CLAUDE.md / codex/AGENTS.md は4つの承認・canonical coordination・file reservationの既存境界を維持するため変更不要と確認した。fleet固有の変更はこのguide、docs/install.md、docs/hooks.md、両READMEに記載。
