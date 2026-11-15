#!/usr/bin/env python3
"""usage-throttle-warn.py — R-068 (1) 自動減速の hook 側（2026-09-23 KindPasteur・I-1）。

PostToolUse on the Workflow tool, head only. When ~/.agentstack/runtime/usage.json
(written by the head on each patrol: {"weekly_pct": 76, "five_hour_pct": 40, "ts": "..."})
says the weekly usage is at or above warn_workflow_weekly_pct, the head is told in
additionalContext that retrospective/audit workflows should stop (R-068). The supervisor
reads the same file to narrow station dispatch to one seat at the higher threshold.
Never blocks, never raises.
"""
import json
import os
import subprocess
import sys

USAGE = os.path.expanduser("~/.agentstack/runtime/usage.json")
CONFIG = os.path.expanduser("~/.agentstack/config/head-send-lint.json")
HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
WARN_WORKFLOW_WEEKLY_PCT = 60


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        with open(CONFIG, encoding="utf-8") as f:
            head = json.load(f)["head_name"]
        sender = subprocess.run(
            ["bash", "-c", f'. "{HOOKS_DIR}/resolve-agent-name.sh" >/dev/null 2>&1; printf %s "$RESOLVED_AGENT"'],
            capture_output=True, text=True, timeout=10).stdout.strip()
        if sender != head or payload.get("hook_event_name") != "PostToolUse":
            return 0
        with open(USAGE, encoding="utf-8") as f:
            usage = json.load(f)
        weekly = float(usage.get("weekly_pct", 0))
        if weekly < WARN_WORKFLOW_WEEKLY_PCT:
            return 0
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"R-068 自動減速: 週次枠 {weekly:.0f}%（usage.json {usage.get('ts', '?')}）。"
                f"{WARN_WORKFLOW_WEEKLY_PCT}% 以上では振り返り・監査の Workflow を止める。"
                "この Workflow がそれに当たるなら止めること。"),
        }}, ensure_ascii=False))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
