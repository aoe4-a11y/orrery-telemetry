#!/usr/bin/env python3
"""Copy the canonical storage text (storage-v6.0.md) into every local mirror's marked section."""
import re
from pathlib import Path
H=Path.home()
new=(H/".agentstack/runtime/storage-v6.0.md").read_text().strip()+"\n"
files=[H/".claude/CLAUDE.md",H/".codex/AGENTS.md",H/".agentstack/runtime/station-template.md",
 H/"tools/osce-trainer-main/AGENTS.md",H/"tools/osce-trainer-main/CLAUDE.md",
 H/"tools/osce-trainer/AGENTS.md",H/"tools/osce-trainer/CLAUDE.md"]
pat=re.compile(r"<!-- BEGIN STORAGE V5 -->\n.*?<!-- END STORAGE V5 -->",re.S)
for f in files:
    t=f.read_text()
    assert len(pat.findall(t))==1, f
    f.write_text(pat.sub(lambda m:"<!-- BEGIN STORAGE V5 -->\n"+new+"<!-- END STORAGE V5 -->",t))
    print("OK",f)
