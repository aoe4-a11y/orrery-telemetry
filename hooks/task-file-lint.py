#!/usr/bin/env python3
"""OPS-1 (d): PreToolUse(Write|Edit) guard for station files.

A station file under ~/.agentstack/runtime/tasks/ that touches import,
assembly, answers or figures must name the P-019 minimum known set and the
"unit before the full run" clause. Read-only stations ("heavy は使わない" /
"heavy なし") are exempt. Exit 2 blocks the write and tells the writer why.
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
    if not TOUCHES.search(text) or READ_ONLY.search(text):
        return 0
    missing = []
    if "P-019" not in text and not all(re.search(p, text) for p in P019_PARTS):
        missing.append("P-019 の最小集合（国試 114〜118 全冊・113B・卒試 2025-1・449）")
    if not UNIT_FIRST.search(text):
        missing.append("「全量の前に unit 全体で赤 0（M-051）」の条項")
    if not missing:
        return 0
    print(
        f"task-file-lint (OPS-1 (d)): {path.name} は取り込み・組み立て・正答・図に触る駅なのに、"
        + "・".join(missing)
        + " が無い。完了の定義に足してから書くこと（読むだけの駅なら「heavy は使わない」と書く）。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
