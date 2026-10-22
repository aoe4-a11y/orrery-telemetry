#!/usr/bin/env python3
"""Verify the retained standalone restore tool on this station's isolated install."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    root=Path(__file__).resolve().parents[1]
    result=json.loads((root/'docs/orrery-up-2/rehearsal.json').read_text())
    home=Path(result['home']);snapshot=Path(result['rollback_snapshot'])
    # The only writable destination is the explicit isolated HOME from rehearsal.
    if not home.is_relative_to(Path('/Users/huyuhutaru/.dev-storage-governor/examforge/20261022T063810Z-build-cache-e4007ade')):
        raise ValueError('not this station isolated HOME')
    for port in (result['mail_port'],result['dashboard_port']):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',port))==0:raise ValueError('helper still running')
    manifest=json.loads((snapshot/'manifest.json').read_text())
    tool=snapshot/'restore-tool.py.txt'
    assert sha(tool)==manifest['restore_tool_sha256']
    stack=home/'.agentstack';payload=stack/'bin/agentstack-restart-seat'
    original=next(r for r in manifest['records'] if r['path']=='.agentstack/bin/agentstack-restart-seat')['sha256']
    database=stack/'mail/storage.sqlite3';before_database=sha(database)
    sentinel=stack/'runtime/rollback-sentinel.txt';sentinel.write_text('isolated runtime state must survive')
    payload.write_text(payload.read_text()+'\n# owned rollback proof mutation\n')
    changed=sha(payload)
    assert changed!=original
    command=subprocess.run([sys.executable,str(tool),'restore','--home',str(home),'--directory',str(snapshot)],check=False)
    proof={'restore_exit':command.returncode,'snapshot_records':len(manifest['records']),
           'mutated_payload_sha256':changed,'expected_payload_sha256':original,'restored_payload_sha256':sha(payload),
           'payload_restored':sha(payload)==original,'isolated_database_unchanged':sha(database)==before_database,
           'runtime_sentinel_preserved':sentinel.read_text()=='isolated runtime state must survive',
           'new_core_alternate_retained':(stack/'hooks/spawn_child.upstream.sh').is_file(),
           'scope':'actual isolated snapshot and standalone restore tool; production paths not written'}
    (root/'docs/orrery-up-2/rollback-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,indent=2))
    assert command.returncode==0 and all(proof[k] for k in ('payload_restored','isolated_database_unchanged','runtime_sentinel_preserved','new_core_alternate_retained'))

if __name__=='__main__':main()
