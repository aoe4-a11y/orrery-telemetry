#!/bin/bash
# Stop hook for the head session (M-037 recurrence 8, 2026-10-04): the head must not end a turn
# without a running fleet watcher, or nothing wakes it and the fleet sits unattended for hours.
# Opt out (e.g. the owner asks the head to stop) by touching ~/.agentstack/runtime/head-wait-optout.
input=$(cat)
case "$input" in *'"stop_hook_active":true'*|*'"stop_hook_active": true'*) exit 0;; esac
[ -e "$HOME/.agentstack/runtime/head-wait-optout" ] && exit 0
# 2026-10-31 15:3x MAIL-CURSOR-1（JUDGE-MAIL-CURSOR-1-2 accept ee11d7c3）: 新版 head-wait-event.v2.sh も見張りとして数える
if pgrep -f 'head-wait-event(\.v2)?\.sh' >/dev/null 2>&1; then exit 0; fi
printf '%s\n' '{"decision":"block","reason":"head-wait-event.sh が走っていない。艦隊の見張りを張り直してから turn を終える: Bash の run_in_background で bash ~/.agentstack/runtime/head-tools/mail-cursor/head-wait-event.v2.sh（読み終えた便は mail_cursor.py record-read --ids で記録・M-037・M-085）。止める必要があるなら ~/.agentstack/runtime/head-wait-optout を作る。"}'
exit 0
