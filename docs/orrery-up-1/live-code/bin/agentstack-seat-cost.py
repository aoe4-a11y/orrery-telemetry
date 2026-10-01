#!/usr/bin/env python3
"""Per-seat token accounting from Codex rollout files.

Usage: agentstack-seat-cost.py [YYYY/MM/DD ...]   (default: today)
Prints one row per rollout: model, effort (if recorded), turns, input/cached/output/reasoning tokens.
Read-only. Token counts come from the rollout's own `total_token_usage` records.
"""
import json, os, sys, glob, collections, datetime

def rows(day):
    base = os.path.expanduser(f"~/.codex/sessions/{day}")
    for p in sorted(glob.glob(base + "/*.jsonl")):
        model = effort = None
        last = None
        turns = 0
        for line in open(p, encoding="utf-8", errors="ignore"):
            if '"model"' in line and model is None:
                try:
                    d = json.loads(line)
                    payload = d.get("payload") or d
                    model = payload.get("model") or model
                    effort = payload.get("model_reasoning_effort") or payload.get("effort") or effort
                except Exception:
                    pass
            if '"total_token_usage"' in line:
                try:
                    d = json.loads(line)
                    s = json.dumps(d)
                    i = s.find('"total_token_usage"')
                    obj = json.loads(s[s.index("{", i + 19):s.index("}", s.index("{", i + 19)) + 1])
                    last = obj
                    turns += 1
                except Exception:
                    pass
        if last:
            yield os.path.basename(p)[:34], model, effort, turns, last

def main():
    days = sys.argv[1:] or [datetime.date.today().strftime("%Y/%m/%d")]
    agg = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    print(f"{'rollout':36} {'model':16} {'eff':6} {'turns':>5} {'in':>9} {'cached':>9} {'out':>8} {'reason':>8}")
    for day in days:
        for name, model, effort, turns, u in rows(day):
            i, c, o, r = (u.get("input_tokens", 0), u.get("cached_input_tokens", 0),
                          u.get("output_tokens", 0), u.get("reasoning_output_tokens", 0))
            print(f"{name:36} {str(model):16} {str(effort):6} {turns:5} {i:9} {c:9} {o:8} {r:8}")
            k = f"{model}/{effort}"
            a = agg[k]
            a[0] += 1; a[1] += turns; a[2] += i; a[3] += o; a[4] += r
    print(f"\n{'model/effort':24} {'runs':>5} {'turns':>6} {'input':>11} {'output':>9} {'reasoning':>10}")
    for k, a in sorted(agg.items(), key=lambda x: -x[1][2]):
        print(f"{k:24} {a[0]:5} {a[1]:6} {a[2]:11} {a[3]:9} {a[4]:10}")

if __name__ == "__main__":
    main()
