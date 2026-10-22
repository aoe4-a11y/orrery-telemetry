#!/bin/bash
# head の待ち（2026-09-29 10:0x 使用量 95%: [receipt]・[blocked]・[env-blocked] の便だけで起きる。[progress] は裁定・相談・停止・失敗などの語を含む物だけで起きる・2026-09-29 使用量対策）: 便（自分宛て・[ack]/[heartbeat] と枠の譲り合いの [progress] を除く）・メモリの見張り役の発動・tmux サーバーの消失・DevSSD と内蔵の床割れ のどれかが起きたら 1 回だけ出力して終わる（30 分ごとの空振りの起床を無くす・2026-09-29 使用量対策）
# 2026-10-20 18:3x: head が `&>/dev/null & disown` で起こすと出力が捨てられ、起きても head に届かない（同じ日に 3 回目）。出力が /dev/null なら起動しない（Bash の run_in_background で起こす）。
if [ /dev/fd/1 -ef /dev/null ]; then echo "head-wait-event.sh: 出力が /dev/null。Bash の run_in_background で起こす（& disown は使わない）" >&2; exit 2; fi
last=${1:-0}
lines=$(wc -l < ~/.agentstack/runtime/memory-guard.log)
floor_note=""
seats0=$(tmux ls 2>/dev/null | wc -l | tr -d ' ')
while true; do
  # CODEX-RESET-1 / R-093 / M-059（2026-10-13 head）: Codex の週の枠が 95% を越えたら 1 時間に 1 回だけ知らせて起きる。ここでリセットはしない。
  cu_tool="$HOME/.agentstack/bin/codex-usage"; cu_stamp="$HOME/.agentstack/runtime/codex-usage-alert.stamp"
  if [ -x "$cu_tool" ] && { [ ! -f "$cu_stamp" ] || [ $(( $(date +%s) - $(stat -f %m "$cu_stamp") )) -ge 3600 ]; }; then
    cu_alert=$("$cu_tool" --warn-above 95 2>/dev/null || true)
    if [ -n "$cu_alert" ]; then touch "$cu_stamp"; printf '%s\n' "$cu_alert"; echo "LAST=$last"; exit 0; fi
  fi
  rows=$(sqlite3 -readonly -separator ' | ' ~/.agentstack/mail/storage.sqlite3 "select m.id, s.name, m.subject from messages m join message_recipients r on r.message_id=m.id join agents a on a.id=r.agent_id join agents s on s.id=m.sender_id where a.name='ProudTuring' and m.id>$last and s.name<>'ProudTuring' and (r.kind<>'cc' or m.subject like '[receipt]%' or m.subject like '[blocked]%' or m.subject like '[env-blocked]%') order by m.id;" 2>/dev/null)
  if [ -n "$rows" ]; then
    last=$(printf '%s\n' "$rows" | tail -1 | cut -d' ' -f1)
    # 2026-10-09 R-084: 駅の中の下請け席（head-wait-ignore-senders に 1 行 1 名）の便では起きない。[blocked] だけは起きる。水位（last）は全部の便で進める
    ign="$HOME/.agentstack/runtime/head-wait-ignore-senders"
    if [ -s "$ign" ]; then
      rows=$(printf '%s\n' "$rows" | awk -F' [|] ' -v f="$ign" 'BEGIN{while((getline l<f)>0) if(l!="") ig[l]=1} { if(($2 in ig) && $3 !~ /^\[(blocked|env-blocked)\]/) next; print }')
    fi
    # 2026-10-12 M-055: 待つ席は [blocked] を出してから turn を終える決まりにしたので、head の判断が要らない資源の待ち
    # （台数・heavy・governor・予約・lock）の [blocked] では起きない。head・裁定・返答・判断などの語があれば起きる。
    hit=$(printf '%s\n' "$rows" | grep -E '\| \[(receipt|blocked|env-blocked|ruling)[^]]*\]' | awk '{ if ($0 ~ /\[blocked[^]]*\]/ && $0 !~ /\[blocked\/ruling/ && $0 ~ /(起動待ち|台数|Booted|heavy|governor|予約|lockの|lock待ち|枠待ち|割当待ち|凍結待ち|overlay待ち|継続待ち|入力待ち|到着待ち|SHA待ち|版待ち|受領待ち|待ち|待つ|待機|保留)/ && $0 !~ /(裁定|返答|回答|判断|照会|相談|指示|割当の返答|決め|お願い|推奨|起こす|別席|無活動|応答なし|読了依頼|検収依頼|検収|probe)/) next; print }')
    # 2026-10-05: [plan]・[progress] でも、head の裁定を求める語があれば起きる（便13238 を 1 時間待たせた・M-037 の類型）
    # 2026-10-14 01:5x: Claude 週 83%。[blocked] の「…待ち」だけの便（head の語が無い）では起きない（水位は進める）。
    # 2026-10-13: head 宛て（to）の [plan] は全部起きる。KindPasteur の「head の答えが要る 4 点」（便23669）など head 宛ての [plan] 7 通を、語の一覧に無い言い方のため最長約 4 時間（15:03〜19:14）見落とした
    [ -n "$hit" ] || hit=$(printf '%s\n' "$rows" | grep -E '\| \[plan\]')
    # 2026-10-16 00:3x M-037: GustyFermi の検収の probe の頼み（[progress]「head probeを」・[blocked]「検収用head probe待ち」）で起きず、席が 300 秒待って配備を戻した。probe・検収・お願いの語で起きる
    [ -n "$hit" ] || hit=$(printf '%s\n' "$rows" | grep -E '\| \[progress\]' | grep -E '裁定待ち|裁定依頼|照会|相談|回答待ち|返答待ち|判断を|依頼|床NG|退行|probe|検収|お願い')
    # 2026-10-06: 監査の赤でも起きる（19:04 の Codex 席の一斉消失を OrreryAudit が 21:37 に赤で出したが、head は 3 時間気づかなかった）
    [ -n "$hit" ] || hit=$(printf '%s\n' "$rows" | grep -E '\| \[audit[^]]*\]' | grep -E '赤')
    # 2026-10-17 04:2x M-039: 統合の席（KindPasteur・P1 の全量）の [progress] と、head への返答（Re:）は件名に語が無くても起きる（便25986 の判断の依頼を本文だけに書かれて 25 分見落とした）
    [ -n "$hit" ] || hit=$(printf '%s\n' "$rows" | awk -F' [|] ' '(($2=="KindPasteur" && $3 ~ /^\[(progress|plan)\]/) || $3 ~ /^Re:/) && $3 !~ /席の見張り/')
    if [ -n "$hit" ]; then printf '%s\n' "$hit"; echo "LAST=$last"; exit 0; fi
  fi
  n=$(wc -l < ~/.agentstack/runtime/memory-guard.log)
  if [ "$n" -gt "$lines" ]; then tail -n $((n-lines)) ~/.agentstack/runtime/memory-guard.log | sed 's/^/MEMORY-GUARD: /' | cut -c1-200; echo "LAST=$last"; exit 0; fi
  tmux ls >/dev/null 2>&1 || { echo "TMUX-SERVER-GONE $(date +%H:%M:%S)"; echo "LAST=$last"; exit 0; }
  # 2026-10-06: 席の session が一度に 2 つ以上消えたら起きる（reaper は 1 つずつ閉じ、便で知らせる）
  seatsn=$(tmux ls 2>/dev/null | wc -l | tr -d ' ')
  if [ "${seatsn:-0}" -le $(( ${seats0:-0} - 2 )) ]; then echo "SEATS-DROPPED ${seats0}->${seatsn} $(date +%H:%M:%S)"; echo "LAST=$last"; exit 0; fi
  [ "${seatsn:-0}" -gt "${seats0:-0}" ] && seats0=$seatsn
  # 2026-10-08: seats that exist but cannot work (login expired / usage limit) and whole-fleet idle.
  STUCKDIR="$HOME/.agentstack/runtime/head-wait-stuck"; mkdir -p "$STUCKDIR"
  anywork=0
  for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null); do
    pane="$(tmux capture-pane -p -t "$s" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -15)"
    echo "$pane" | grep -q -E 'Working \(|· esc to interrupt' && anywork=1
    why=""
    echo "$pane" | grep -q -E 'Login expired|Please run /login|Not logged in' && why="login-expired"
    [ -z "$why" ] && echo "$pane" | grep -q -i -E "usage limit|hit your limit|rate limit reached|limit reached" && why="usage-limit"
    if [ -n "$why" ] && [ ! -f "$STUCKDIR/$s.$why" ]; then
      touch "$STUCKDIR/$s.$why"; echo "SEAT-STUCK $s $why $(date +%H:%M:%S)"; echo "LAST=$last"; exit 0
    fi
    [ -z "$why" ] && rm -f "$STUCKDIR/$s".* 2>/dev/null
  done
  heavy=$(pgrep -f 'xcodebuild|heavy_job_lock' 2>/dev/null | wc -l | tr -d ' ')
  if [ "$anywork" = 0 ] && [ "${heavy:-0}" = 0 ]; then
    [ -f "$STUCKDIR/fleet-idle-since" ] || date +%s > "$STUCKDIR/fleet-idle-since"
    since=$(cat "$STUCKDIR/fleet-idle-since"); now=$(date +%s)
    if [ $(( now - since )) -ge 2700 ] && [ ! -f "$STUCKDIR/fleet-idle-reported" ]; then
      touch "$STUCKDIR/fleet-idle-reported"; echo "FLEET-IDLE $(( (now - since) / 60 ))min $(date +%H:%M:%S)"; echo "LAST=$last"; exit 0
    fi
  else
    rm -f "$STUCKDIR/fleet-idle-since" "$STUCKDIR/fleet-idle-reported"
  fi
  [ -n "${SKIP_FLOOR:-}" ] || for v in /Volumes/DevSSD /System/Volumes/Data; do
    pct=$(df -k "$v" 2>/dev/null | awk 'NR==2 {printf "%d", $4*100/$2}')
    if [ -n "$pct" ] && [ "$pct" -lt 10 ]; then echo "FLOOR $v free=${pct}% $(date +%H:%M)"; echo "LAST=$last"; exit 0; fi
  done
  sleep 30
done
