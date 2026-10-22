#!/usr/bin/env python3
"""Read-only replay of logged alerts against outgoing metadata at each alert.

32536: SELECT id/subject/created_ts only; no message bodies or recipient inboxes.
No mail or state changes. The current ignore file is explicit, not reconstructed
historical ignore membership. Existing logged alerts already passed old gates.
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from agentstack_stallself import DB, decision, last_outgoing


def replay(log_path, day, through, ignore_path, db=DB):
    raw=Path(log_path).read_bytes();cutoff=datetime.datetime.fromisoformat(through.replace('Z','+00:00'))
    if cutoff.tzinfo is None:raise ValueError('timezone required for cutoff')
    ignore_raw=Path(ignore_path).read_bytes() if Path(ignore_path).exists() else b''
    ignored={x.split('#',1)[0].strip() for x in ignore_raw.decode().splitlines()}-{''}
    pattern=re.compile(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] alert ([A-Za-z][A-Za-z0-9_-]*) unchanged (\d+) min$')
    rows=[]
    for line in raw.decode().splitlines():
        match=pattern.fullmatch(line)
        if not match or not match.group(1).startswith(day):continue
        local=datetime.datetime.strptime(match.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Tokyo'))
        if local>cutoff:continue
        seat=match.group(2);latest=last_outgoing(seat,before=local.isoformat(),db=db)
        allowed,reason=decision(latest,seat in ignored)
        rows.append(dict(alert_at=local.isoformat(),seat=seat,minutes=int(match.group(3)),would_send=allowed,reason=reason,last_outgoing=latest))
    return dict(day=day,through=cutoff.isoformat(),log_path=str(log_path),source_log_sha256=hashlib.sha256(raw).hexdigest(),source_log_bytes=len(raw),ignore_path=str(ignore_path),ignore_sha256=hashlib.sha256(ignore_raw).hexdigest(),ignore_scope='current file only; historical membership unmeasured; original log alerts passed the then-current ignore gate',alert_count=len(rows),would_send=sum(x['would_send'] for x in rows),would_not_send=sum(not x['would_send'] for x in rows),reasons=dict(collections.Counter(x['reason'] for x in rows)),rows=rows,db_scope='read-only SELECT outgoing id/subject/created_ts by sender and <=alert time; all recipient sets; no body/inbox reads',sent_messages=0)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--day',required=True);p.add_argument('--through',required=True);p.add_argument('--expected-alerts',type=int,default=45);p.add_argument('--log',type=Path,default=Path.home()/'.agentstack/runtime/seat-stall-watch.log');p.add_argument('--ignore',type=Path,default=Path.home()/'.agentstack/runtime/seat-stall-ignore.txt');p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    report=replay(args.log,args.day,args.through,args.ignore)
    if report['alert_count']!=args.expected_alerts:raise ValueError('bounded alert count differs: '+str(report['alert_count']))
    if args.out.exists():raise ValueError('output already exists')
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if os.environ.get('SEAT_STALL_DRYRUN')=='1':
        for row in report['rows']:
            ident=row['last_outgoing']['id'] if row['last_outgoing'] else 'none'
            print('DRYRUN replay '+('send' if row['would_send'] else 'skip')+' seat='+row['seat']+' last='+str(ident)+' reason='+row['reason'])
    print(json.dumps({k:report[k] for k in ['alert_count','would_send','would_not_send','reasons','sent_messages']},ensure_ascii=False))


if __name__=='__main__':main()
