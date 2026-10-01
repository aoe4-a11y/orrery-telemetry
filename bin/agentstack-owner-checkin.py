#!/usr/bin/env python3
"""OPS-1 (f): the nightly one line for the owner (R-070).

  agentstack-owner-checkin.py write   # 21:00 — writes owner-checkin-YYYY-MM-DD.txt
  agentstack-owner-checkin.py verify  # 21:05 — if today's line is missing, marks the
                                      #          status board red and mails head

Sources (head keeps the two text files; a missing file is reported as 未確認):
  ~/.agentstack/runtime/owner-ipad-version.txt  first line = the build the owner last reported
  ~/.agentstack/runtime/owner-pending.txt        one line per decision waiting on the owner
  readable explanations = bundled explanations in the newest examforge-v* TestFlight tag
"""
import datetime
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

RUNTIME = Path.home() / ".agentstack/runtime"
REPO = Path.home() / "tools/examforge-wt-first-experience"
DB = Path.home() / ".agentstack/mail/storage.sqlite3"
RED = RUNTIME / "status-red.txt"


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout


def first_line(path):
    try:
        return next((l.strip() for l in path.read_text().splitlines() if l.strip()), None)
    except OSError:
        return None


def readable_explanations():
    tags = [t for t in git("tag", "--list", "examforge-v*", "--sort=-creatordate").split() if t]
    if not tags:
        return "未確認（TestFlight の tag が無い）"
    tag = tags[0]
    total = 0
    for path in git("ls-tree", "-r", "--name-only", tag, "apps/ios/Resources/PublicPacks").split():
        if path.endswith("exam-pack.json"):
            pack = json.loads(git("show", f"{tag}:{path}"))
            total += sum(bool(((q.get("explanation") or {}).get("text") or "").strip()) for q in pack["questions"])
    return f"{total} 本（{tag}）"


def write(today):
    ipad = first_line(RUNTIME / "owner-ipad-version.txt") or "未確認（殿の報告の記録なし）"
    try:
        pending = [l for l in (RUNTIME / "owner-pending.txt").read_text().splitlines() if l.strip()]
        pending_text = f"{len(pending)} 件" + (f"（{'・'.join(pending)}）" if pending else "")
    except OSError:
        pending_text = "未確認（記録なし）"
    now = datetime.datetime.now()
    line = (f"{now:%Y-%m-%d %H:%M} JST（R-070 の毎晩の 1 行・OPS-1 (f) 自動）\n"
            f"殿の iPad: {ipad}。読める解説: {readable_explanations()}。殿の判断待ち: {pending_text}\n")
    (RUNTIME / f"owner-checkin-{today}.txt").write_text(line)
    print(line, end="")


def verify(today):
    if (RUNTIME / f"owner-checkin-{today}.txt").exists():
        return
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    RED.write_text(f"赤 {stamp}: owner-checkin-{today}.txt が 21:05 に無い（OPS-1 (f)）\n")
    con = sqlite3.connect(DB, timeout=30)
    cur = con.cursor()
    sender = cur.execute("select id from agents where name='KindPasteur'").fetchone()[0]
    head = cur.execute("select id from agents where name='ProudTuring'").fetchone()[0]
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    cur.execute(
        "insert into messages(project_id, sender_id, thread_id, topic, subject, body_md, importance, "
        "ack_required, created_ts, attachments) values (1,?,NULL,NULL,?,?,'high',0,?,'[]')",
        (sender, f"[blocked] 毎晩の 1 行が 21:05 に無い（owner-checkin-{today}.txt）",
         f"{RED} に赤を書いた。21:00 の自動書き出しが失敗したとみられる（~/.agentstack/runtime/owner-checkin.err を見る）。", now))
    cur.execute("insert into message_recipients(message_id, agent_id, kind) values (?,?,'to')", (cur.lastrowid, head))
    con.commit()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "write"
    today = datetime.date.today().isoformat()
    {"write": write, "verify": verify}[mode](today)
