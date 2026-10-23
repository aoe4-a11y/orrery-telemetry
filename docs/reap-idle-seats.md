# 席を閉じる際の process 保護

台帳: M-079・M-018。`bin/agentstack-reap-idle-seats` は、
自動片づけと `--close SEAT REASON` の両方で同じ停止フィルターを使う。

- pane の子孫、`AGENT_NAME`、governor root 名による広い帰属は、
  自動片づけの「仕事があれば席を残す」判定にそのまま使う。
- 同じ ps snapshot で、生きている全 tmux 席の帰属を照合する。
  他席にも帰属する PID は停止せず、PID・理由・相手席名を log と head 向け報告に残す。
- SWBBuildService、XCBBuildService、CoreSimulatorService、launchd_sim、
  SimulatorTrampoline、simdiskimaged と、それらの子孫は停止しない。
- Simulator device path または SIMULATOR_UDID / DEVICE_NAME / ROOT 環境変数で
  識別した process とその子孫も保護する。この道具には device 専有を証明する機構が
  ないため、Simulator process を常に保護する。
- 保護対象が対象席の pane 配下にいる場合は close 自体を拒否する。
  `kill-session` による間接的な SIGHUP も避けるためで、強制 close も例外にしない。
  拒否は非 0 exit と log・head 向け報告で分かる。
- heavy ticket/slot の PID も同じ停止フィルターを通す。他席の owner がある entry、
  または保護 PID に対応する entry は消さない。
- 生きている席の pane または ps を読めなければ停止しない。

`--attribute SEAT` は読み取り用。行は TAB 区切りで、次を含む。

| 種別 | 意味 |
|---|---|
| work | 従来の広い帰属による仕事。argv/env は出さず PID と固定ラベルだけ表示 |
| rule | work PID に当たった pane / AGENT_NAME / root 規則 |
| heavy | 広い帰属による heavy entry（従来どおり） |
| protected | PID、保護理由、他の生存席名（なければ -） |
| close-blocked | pane 依存のため close を拒否する PID |
| stop | 保護を除いた停止候補 PID |
| remove-heavy / protected-heavy | 削除候補 / 保存する heavy entry |

停止候補は読取時点の snapshot に基づく。これは OS の process 所有権の証明や、
将来の process・tmux 状態変更を排除するロックではない。

## 隔離試験

`python3 tests/test_reap_idle_seats.py` は stdlib だけで実行できる。
ps・tmux・kill・sleep・sqlite3 CLI は偽物に置き換え、通知用 DB も一時 fixture のみを使う。
REAP_PS / REAP_KILL はこの隔離試験のための差し替え口。
live の tmux・process・Mail DB には接続しない。
