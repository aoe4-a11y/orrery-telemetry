#!/usr/bin/env bash
# 席が HANDOFF-<名前>-<日付>.md を書いて入力待ちになったら、その席を新しい model で建て直す（head 2026-10-01）。
# 使い方: auto-restart-on-handoff.sh <日付> <model> <effort> <workdir> <席名>...
set -u
DAY="$1"; MODEL="$2"; EFFORT="$3"; WD="$4"; shift 4
T=$HOME/.agentstack/runtime/tasks; LOG=$HOME/.agentstack/runtime/auto-restart-$DAY.log
pending=("$@"); deadline=$(( $(date +%s) + 8*3600 ))
while [ ${#pending[@]} -gt 0 ] && [ "$(date +%s)" -lt "$deadline" ]; do
  left=()
  for s in "${pending[@]}"; do
    f="$T/HANDOFF-$s-$DAY.md"
    pane=$(tmux capture-pane -p -t "$s" 2>/dev/null | tail -8)
    if [ -s "$f" ] && ! printf '%s' "$pane" | grep -qE 'Working \(|Waiting for background|esc to interrupt'; then
      sleep 20  # 書きかけの保存を待つ
      pane=$(tmux capture-pane -p -t "$s" 2>/dev/null | tail -8)
      if printf '%s' "$pane" | grep -qE 'Working \(|esc to interrupt'; then left+=("$s"); continue; fi
      echo "$(date '+%F %T') restart $s with $f ($MODEL $EFFORT)" >> "$LOG"
      "$HOME/.agentstack/bin/agentstack-restart-seat" "$s" "$f" "$MODEL" "$EFFORT" "$WD" >> "$LOG" 2>&1
      echo "$(date '+%F %T') restart $s exit=$?" >> "$LOG"
      echo "RESTARTED $s"
    else
      left+=("$s")
    fi
  done
  pending=("${left[@]+"${left[@]}"}")
  [ ${#pending[@]} -gt 0 ] && sleep 60
done
echo "DONE pending=${pending[*]+${pending[*]}}"
