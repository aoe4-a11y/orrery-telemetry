# ORRERY-UP-2 殿の端末で行う更新手順

台帳: R-005 / R-026 / R-061 / R-084 / R-095 (storage v6.0・2026-10-19) / M-018 / M-020。追加の根拠: head便35253・35265・35273。

この駅は更新の準備だけを行った。本物の install は次の手順を殿が Terminal.app で対話実行する。稼働中の Mail は `--mail keep` でそのまま使う。Mail の build 更新と DB 移行はこの操作に含めない。

1. Spotlight（⌘ Space）で「ターミナル」を開く。head が進行中の起動操作を終えたことを確認してから、次の1行を貼って Enter を押す。

```sh
/bin/bash <(git -C /Users/huyuhutaru/tools/orrery-telemetry show fork/upgrade/orrery-up-2-20261022:scripts/run-fleet-upgrade-from-ref.sh)
```

2. 最初に `Rollback snapshot:` と SHA-256 が表示される。旧 payload・env・settings・managed documents・世代別 release・明示した runtime script は暗号化 DevSSD-Private に退避される。Mail DB・runtime の資格情報は退避・変更しない。退避に失敗した場合は installer に進まない。この snapshot の絶対 path を控える。
3. installer の差分を読む。settings の統合、`~/.claude.json` の MCP 設定、Codex の managed AGENTS block、Claude の managed CLAUDE block の承認が聞かれる。それぞれ表示された対象が今回の環境であることを確認し、適用する場合は小文字の `yes` と Enter。承認しない場合は `no` とし、その対象は未更新として head に伝える。`--assume-yes` は使わない。
4. 最後の `Fleet installer exit:` と `Fleet doctor exit:`、`Rollback snapshot:` の path、warning/error を head に伝える。送る文は「ORRERY-UP-2 を端末で実行しました。installer exit は …、doctor exit は …。Rollback snapshot は …。警告は …。」でよい。doctor が非ゼロなら更新確認は完了扱いにしない。head が実際の endpoint・起動・通知の結果を確認する。

bootstrap は専用の管理 worktree を作り、終了後に clean なら取り除く。殿が利用した snapshot 内に `restore-tool.py.txt` を残すため、準備用 worktree を片づけても次の戻し方を使える。

## 戻し方（3行）

表示された snapshot の絶対 path で `<SNAPSHOT>` を置き換える。

```sh
python3 '<SNAPSHOT>/restore-tool.py.txt' restore --home /Users/huyuhutaru --directory '<SNAPSHOT>'
/Users/huyuhutaru/.agentstack/dashboard/agentctl.sh restart
/Users/huyuhutaru/.agentstack/bin/agentstack-doctor
```

restore は manifest の全対象 SHA-256 を先に確認して旧 bytes を戻す。Mail DB・token・新規 runtime state を戻さず、新版が新規に追加した file も削除しない。dashboard の restart だけを行う。既存の各席や watcher の process を新しい code に読み直させる操作、実端末での rollback は未測定。

## 今回の起動経路

既定の `hooks/spawn_child.sh` は head便35265で承認した compatibility dispatcher。現行の `releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595` の5 regular fileと3 symlink（計8件）を保存し、Claude/Codex の起こし方を維持する。本家最新の core は `hooks/spawn_child.upstream.sh` と `hooks/cleanup-child-agent.upstream.sh` にも置く。coreへの切替は別の駅で行う。所有者の通常の更新手順では切り替えない。

`AGENTSTACK_CODEX_BIN` の native-TLS wrapper 指定と直前の注記2行を installer の env 再生成でも保持する。外部の `~/.local/bin/codex-native-tls` と global git の `http.sslCAInfo` は、この install では上書きしない。TLS の根拠は head便35273・ENV-UP-2 の実測。ここで測るのは wrapper の設定保持と子process環境で、実ネットワークの証明は未測定。

隔離試験は HOME・install-dir・scoped と専用portを使い、service manager/tmux検出を Linux stub にし、PATHのpkill・killallは拒否stubにした。`--scoped` により承認対象の user設定を追加していない。launchd・所有者の対話承認・本番fleet全席再起動は未測定。
