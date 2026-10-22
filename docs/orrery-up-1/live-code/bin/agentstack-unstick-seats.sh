#!/bin/bash
# Wake Codex tmux seats that ended a turn with notifications still queued
# ("Messages to be submitted after next tool call") and are idle at the prompt.
# Sends a single Enter to that pane so the queued mail notifications submit. Read-only otherwise.
LOG="$HOME/.agentstack/runtime/unstick-seats.log"
for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null); do
  pane="$(tmux capture-pane -p -t "$s" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -12)"
  echo "$pane" | grep -q 'submitted after next tool call' || continue
  echo "$pane" | grep -q -E 'Working \(|esc to interrupt' && continue
  # 2026-09-11: Claude 席も対象にする（Codex 限定だったためチェーンが止まった）
  echo "$pane" | tail -4 | grep -qE 'Ask Codex to do anything|auto mode on|bypass permissions|accept edits' || continue
  tmux send-keys -t "$s" Enter
  echo "[$(date '+%F %T')] unstick: $s" >> "$LOG"
done
exit 0
