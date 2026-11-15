#!/bin/zsh
# retire-drain.sh — head 2026-10-14 (DELETE-CAUSE-3 受理 便24388 の後・RETIRE-HOLD 解除)
# retire-pending.txt の駅を 1 つずつ head-accept --reuse-accept で retire する（nice 19・逐次）。
# 止まる条件: STOP file がある / RETIRE-HOLD が戻った / どれかの apply_exit が 0 でない。
# 下見の失敗（preview_exit != 0）は何も消さないので記録して次へ進む。
set -u
WORK=$HOME/.agentstack/runtime/head-accept
PENDING=$WORK/retire-pending.txt
STOP=$WORK/RETIRE-DRAIN-STOP
LOG=$WORK/retire-drain-$(date +%Y%m%dT%H%M%S).log
DONE=$WORK/retire-drain-done.txt
touch "$DONE"
echo "start $(date '+%F %T') pending=$(wc -l < "$PENDING")" >> "$LOG"
awk '!seen[$1]++ {print $1, $2}' "$PENDING" | while read -r station rid; do
  [ -e "$STOP" ] && { echo "stop file $(date '+%T')" >> "$LOG"; break; }
  [ -e "$WORK/RETIRE-HOLD" ] && { echo "RETIRE-HOLD present $(date '+%T')" >> "$LOG"; break; }
  grep -qx "$station $rid" "$DONE" && continue
  echo "== $station $rid $(date '+%T')" >> "$LOG"
  out=$(nice -n 19 $HOME/.agentstack/bin/head-accept "$station" "$rid" --reuse-accept 2>&1)
  rc=$?
  printf '%s\n' "$out" | tail -40 >> "$LOG"
  summary=$(printf '%s\n' "$out" | sed -n 's/^summary: //p' | tail -1)
  if [ -n "$summary" ] && python3 -c "
import json,sys
rows=json.load(open(sys.argv[1]))
bad=[r for r in rows if 'apply_exit' in r and r['apply_exit']!=0]
sys.exit(1 if bad else 0)" "$summary"; then
    echo "$station $rid" >> "$DONE"
  elif [ -n "$summary" ]; then
    echo "APPLY FAILED $station — drain stopped $(date '+%T')" >> "$LOG"; break
  else
    echo "no summary rc=$rc $station — drain stopped $(date '+%T')" >> "$LOG"; break
  fi
done
echo "end $(date '+%F %T')" >> "$LOG"
df -k /Volumes/DevSSD /Volumes/DevSSD-Private / >> "$LOG"
