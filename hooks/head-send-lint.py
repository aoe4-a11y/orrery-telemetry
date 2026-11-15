#!/usr/bin/env python3
"""head-send-lint.py — R-068 (2) head の送信前検査（2026-09-23 KindPasteur・I-1）。

Registered for BOTH PreToolUse and PostToolUse on mcp__orrery-mail__send_message.
Only the head's sends are checked; every other sender passes untouched.

  until warn_until_jst : PostToolUse returns the findings as additionalContext
                         (the mail is already sent — warning only);
                         PreToolUse does nothing.
  after warn_until_jst : PreToolUse blocks (exit 2, findings on stderr);
                         PostToolUse does nothing.

Checks (config: ~/.agentstack/config/head-send-lint.json):
  1. a question/choice count without its (import/run, HEAD, iOS) basis
  2. a term of a major ruling without that ruling's ID in the mail
  3. a 「…」 quoted right after 殿 that is not a substring of the owner's
     actual words (index built by ~/.agentstack/bin/owner-quote-index)

Never raises: any internal error exits 0 so a broken lint cannot stop mail.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

CONFIG = os.environ.get("HEAD_SEND_LINT_CONFIG") or os.path.expanduser("~/.agentstack/config/head-send-lint.json")
HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_BUILDER = os.path.expanduser("~/.agentstack/bin/owner-quote-index")


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def resolve_sender(payload):
    """The bound ORRERY identity of this session (same resolver as the other guards)."""
    try:
        out = subprocess.run(
            ["bash", "-c", f'. "{HOOKS_DIR}/resolve-agent-name.sh" >/dev/null 2>&1; printf %s "$RESOLVED_AGENT"'],
            capture_output=True, text=True, timeout=10).stdout.strip()
        if out:
            return out
    except Exception:
        pass
    session_id = payload.get("session_id") or ""
    index_dir = os.path.expanduser("~/.agentstack/runtime/session_index")
    try:
        for name in os.listdir(index_dir):
            with open(os.path.join(index_dir, name), encoding="utf-8") as f:
                entry = json.load(f)
            if entry.get("session_id") == session_id:
                return entry.get("agent_name") or ""
    except Exception:
        pass
    return ""


def norm(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def check_counts(text, cfg):
    findings = []
    basis = {k: re.compile(v, re.I) for k, v in cfg["count_basis_patterns"].items()}
    # A basis line ("基盤…") carrying all three covers the whole mail.
    for line in text.splitlines():
        if "基盤" in line and all(p.search(line) for p in basis.values()):
            return findings
    window = int(cfg.get("count_basis_window_chars", 160))
    seen = set()
    for pattern in cfg["count_patterns"]:
        for m in re.finditer(pattern, text):
            if m.start() in seen:
                continue
            seen.add(m.start())
            around = text[max(0, m.start() - window): m.end() + window]
            missing = [k for k, p in basis.items() if not p.search(around)]
            if missing:
                findings.append(f"① 数字「{m.group(0)}」に基盤が無い（欠け: {', '.join(missing)}）")
    return findings


def check_ruling_terms(text, cfg):
    findings = []
    for ruling, terms in cfg["ruling_terms"].items():
        if ruling in text:
            continue
        hits = [t for t in terms if re.search(t, text, re.I)]
        if hits:
            findings.append(f"② 裁定語 {hits[:3]} があるのに {ruling} の引用が無い")
    return findings


def owner_index(cfg):
    path = os.path.expanduser(cfg["owner_quote_index"])
    max_age = int(cfg.get("owner_quote_index_max_age_seconds", 600))
    try:
        stale = time.time() - os.path.getmtime(path) > max_age
    except OSError:
        stale = True
    if stale and os.path.exists(INDEX_BUILDER):
        subprocess.run([sys.executable, INDEX_BUILDER], capture_output=True, timeout=60)
    try:
        with open(path, encoding="utf-8") as f:
            return norm(f.read())
    except OSError:
        return None


def check_owner_quotes(text, cfg):
    marker = cfg.get("owner_marker", "殿")
    gap = int(cfg.get("owner_quote_max_gap_chars", 24))
    min_chars = int(cfg.get("owner_quote_min_chars", 4))
    quotes = re.findall(re.escape(marker) + r"[^「」\n]{0,%d}「([^」]+)」" % gap, text)
    quotes = [q for q in quotes if len(norm(q)) >= min_chars]
    if not quotes:
        return []
    corpus = owner_index(cfg)
    if corpus is None:
        return ["③ 殿の発言の索引が読めない（owner-quote-index 未生成）— 引用は未照合"]
    findings = []
    for quote in quotes:
        pieces = [norm(p) for p in re.split(r"…+|\.\.\.+|（略）", quote)]
        if not all(p in corpus for p in pieces if p):
            findings.append(f"③ 殿の引用「{quote[:40]}」が殿の実入力に見つからない")
    return findings


TASK_PATH = re.compile(r"~/\.agentstack/runtime/tasks/([A-Za-z0-9._-]+\.md)")


def check_task_files(text):
    """M-069: a station mail must not point at a task file that does not exist yet."""
    findings = []
    for name in sorted(set(TASK_PATH.findall(text))):
        path = os.path.expanduser("~/.agentstack/runtime/tasks/" + name)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            findings.append(f"④ 駅の本文 {name} がまだ無い（書いてから送る・M-069）")
    return findings


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        cfg = load_config()
    except Exception:
        return 0
    try:
        event = payload.get("hook_event_name", "")
        if resolve_sender(payload) != cfg["head_name"]:
            return 0
        until = datetime.datetime.fromisoformat(cfg["warn_until_jst"])
        warning_phase = datetime.datetime.now(datetime.timezone.utc) <= until
        if warning_phase and event != "PostToolUse":
            return 0
        if not warning_phase and event != "PreToolUse":
            return 0
        tool_input = payload.get("tool_input") or {}
        text = (tool_input.get("subject") or "") + "\n" + (tool_input.get("body_md") or "")
        findings = (check_counts(text, cfg) + check_ruling_terms(text, cfg)
                    + check_owner_quotes(text, cfg) + check_task_files(text))
        if not findings:
            return 0
        head = "R-068 送信前検査（{}）: {} 件".format(
            "警告のみ・09-26 まで" if warning_phase else "送信を止めました", len(findings))
        message = head + "\n" + "\n".join("- " + f for f in findings[:12])
        if warning_phase:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse", "additionalContext": message}},
                ensure_ascii=False))
            return 0
        print(message, file=sys.stderr)
        return 2
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
