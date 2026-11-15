#!/usr/bin/env python3
"""M-095: PreToolUse(Write|Edit) note for station files.

A station file under ~/.agentstack/runtime/tasks/ should carry a
「殿の方針の照らし」 section that maps the owner's principles
(~/.agentstack/runtime/OWNER-PRINCIPLES.md, P1-P12) to this station.
Warn only (exit 0); the write is never blocked (M-069).
The older OPS-1 (d) P-019 / unit-first nudge was superseded on 2026-10-28.
"""
import json
import re
import sys
from pathlib import Path

TASKS = Path.home() / ".agentstack/runtime/tasks"
TOUCHES = re.compile(
    r"取り込み|組み立て|正答|別冊の図|図の|figure|import|assembl|NativeExamCompiler|"
    r"NativeQuestionAssembler|NativeImageExtractor|PageTextRecognition|NativeOMR",
    re.IGNORECASE,
)
READ_ONLY = re.compile(r"heavy\s*は使わない|heavy\s*なし|heavy\s*は\s*unit\s*(の確認)?だけ")
P019_PARTS = [r"114", r"118", r"113B", r"2025-1", r"449"]
UNIT_FIRST = re.compile(r"全量の前.{0,12}unit|unit.{0,20}全量の前")


def resulting_text(tool: str, args: dict, path: Path) -> str:
    if tool == "Write":
        return args.get("content", "")
    current = path.read_text() if path.exists() else ""
    old, new = args.get("old_string", ""), args.get("new_string", "")
    if not old:
        return current + new
    return current.replace(old, new) if args.get("replace_all") else current.replace(old, new, 1)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    tool = event.get("tool_name", "")
    args = event.get("tool_input", {}) or {}
    raw = args.get("file_path")
    if tool not in ("Write", "Edit") or not raw:
        return 0
    path = Path(raw).expanduser()
    try:
        path.resolve().relative_to(TASKS.resolve())
    except ValueError:
        return 0
    if path.suffix != ".md":
        return 0
    text = resulting_text(tool, args, path)
    # M-095 (10-28, owner approved 18:5x): the P-019 / unit-first nudges pushed every station toward
    # the full gate the owner moved to one pre-ship run (R-107・R-113・R-120・R-129 の 4). Ask for the
    # owner-principles section instead. Warn only; never block the write (M-069).
    if "殿の方針の照らし" in text or path.name.startswith(("JUDGE-", "FAILING-SET", "TF-36-RUNBOOK")):
        return 0
    missing = ["「殿の方針の照らし」の節（~/.agentstack/runtime/OWNER-PRINCIPLES.md の P1〜P12 のうち、この駅に関わる行ごとに守り方を 1 行）"]
    print(
        f"task-file-lint (M-095): {path.name} に "
        + "・".join(missing)
        + " が無い。足してから席へ送ること（注意だけ・書くのは止めない。"
        "配る前の関門は両 OS の全 unit と殿の iPad の 12 冊だけ・P-019 の全冊と 43 冊の比べは配った後"
        "（R-113）・駅の確かめはできなかった問だけ・殿の方針 P2）。",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
