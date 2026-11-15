#!/usr/bin/env python3
"""M-118: synthetic crash schemas, episode delivery and privacy canaries."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

BIN=Path(__file__).resolve().parent


class CrashTests(unittest.TestCase):
    def setUp(self):
        loader=importlib.machinery.SourceFileLoader('sim_crashes',str(BIN/'agentstack-sim-crash-watch'))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        self.mod=importlib.util.module_from_spec(spec);loader.exec_module(self.mod)
        self.tmp=tempfile.TemporaryDirectory(prefix='fleetmem2-crash-')
        self.root=Path(self.tmp.name);self.reports=self.root/'reports';self.reports.mkdir()
        self.runtime=self.root/'runtime';self.runtime.mkdir()
        self.now=1800000000.;self.sent=[]

    def tearDown(self):
        if hasattr(self,'tmp'):self.tmp.cleanup()

    def report(self,name,at=None,bundle='org.examforge.TealDarwin',simulator=True,incident=None,**updates):
        at=self.now if at is None else at
        h=dict(timestamp=datetime.fromtimestamp(at,timezone.utc).isoformat(),bundleID=bundle,
               incident_id=incident or name,bug_type='309')
        d=dict(captureTime=h['timestamp'],bundleInfo={'CFBundleIdentifier':bundle},
               procPath=('/Library/Developer/CoreSimulator/Devices/opaque/data/App' if simulator else '/Applications/Host.app/App'),
               exception={'type':'EXC_BAD_ACCESS','codes':'PRIVATE_CANARY'},faultingThread=0,
               threads=[{'frames':[{'symbol':'first_symbol','imageOffset':123},{'symbol':'PRIVATE_CANARY'}]}],
               secret='PRIVATE_CANARY',userID='PRIVATE_CANARY',procName='PRIVATE_CANARY')
        d.update(updates)
        p=self.reports/(name+'.ips');p.write_text(json.dumps(h)+'\n'+json.dumps(d));os.utime(p,(at,at))
        return p

    def scan(self,now=None,sender=None):
        return self.mod.scan(self.runtime,self.reports,self.now if now is None else now,
                             sender=sender or (lambda recipient,fields:self.sent.append((recipient,fields))),
                             owners=['TealDarwin','EmeraldCurie','ProudDirac'])

    def test_two_crashes_notify_head_and_owner_once(self):
        self.report('one',self.now-20);self.report('two')
        self.scan();self.scan();self.report('three',self.now+10);self.scan(self.now+10)
        self.assertEqual([x[0] for x in self.sent],['ProudTuring','TealDarwin'])
        fields=self.sent[0][1]
        self.assertEqual(set(fields),{'bundle_id','count','times','exception','first_symbol'})
        self.assertEqual(fields['count'],2);self.assertEqual(len(fields['times']),2)
        self.assertEqual(fields['exception'],'EXC_BAD_ACCESS');self.assertEqual(fields['first_symbol'],'first_symbol')
        self.assertNotIn('PRIVATE_CANARY',json.dumps(self.sent))
        self.assertNotIn('PRIVATE_CANARY',(self.runtime/'sim-crash-state.json').read_text())

    def test_single_crash_and_host_crashes_do_not_notify(self):
        self.report('one');self.report('host1',simulator=False);self.report('host2',simulator=False)
        self.scan();self.assertEqual(self.sent,[])

    def test_separate_bundle_and_old_reports_do_not_accumulate(self):
        self.report('one');self.report('other',bundle='org.other.App')
        self.report('old',self.now-1000)
        self.scan();self.assertEqual(self.sent,[])

    def test_new_episode_after_quiet_period(self):
        self.report('one',self.now-20);self.report('two');self.scan()
        self.report('next1',self.now+601);self.scan(self.now+601)
        self.assertEqual(len(self.sent),2)
        self.report('next2',self.now+620);self.scan(self.now+620)
        self.assertEqual(len(self.sent),4)

    def test_copied_report_is_one_incident(self):
        p=self.report('one');copy=self.reports/'copy.ips';copy.write_bytes(p.read_bytes());os.utime(copy,(self.now,self.now))
        self.scan();self.assertEqual(self.sent,[])

    def test_unknown_delivery_is_not_retried(self):
        calls=[]
        def lose(recipient,fields):calls.append(recipient);raise RuntimeError('PRIVATE_CANARY')
        self.report('one',self.now-20);self.report('two')
        self.scan(sender=lose);self.scan(sender=lose)
        self.assertEqual(calls,['ProudTuring','TealDarwin'])
        self.assertNotIn('PRIVATE_CANARY',(self.runtime/'sim-crash-state.json').read_text())

    def test_owner_matching_and_ambiguity(self):
        for bundle,expected in [('org.examforge.teal-darwin','TealDarwin'),
                                ('org.examforge.nottealdarwin',None),
                                ('org.examforge.TealDarwin.ProudDirac',None)]:
            self.assertEqual(self.mod.owner_for(bundle,['TealDarwin','ProudDirac']),expected)

    def test_unknown_owner_notifies_only_head(self):
        self.report('one',self.now-20,bundle='org.examforge.Unassigned')
        self.report('two',bundle='org.examforge.Unassigned');self.scan()
        self.assertEqual([x[0] for x in self.sent],['ProudTuring'])

    def test_malformed_and_future_reports_skip_without_raw_errors(self):
        (self.reports/'broken.ips').write_text('PRIVATE_CANARY')
        self.report('future',self.now+600);self.report('one')
        self.scan();self.assertEqual(self.sent,[])

    def test_bad_symbol_and_exception_never_forward_private_values(self):
        for i in range(2):
            self.report(str(i),self.now-i,exception={'type':'/Users/private/PRIVATE_CANARY'},
                        threads=[{'frames':[{'symbol':'/Users/private/PRIVATE_CANARY\nsecret'}]}])
        self.scan();self.assertEqual(len(self.sent),2)
        self.assertNotIn('PRIVATE_CANARY',json.dumps(self.sent))
        self.assertEqual(self.sent[0][1]['first_symbol'],'unknown')
        self.assertEqual(self.sent[0][1]['exception'],'unknown')

    def test_unsymbolicated_frames_before_first_symbol(self):
        for i in range(2):
            self.report(str(i),self.now-i,threads=[{'frames':[{'imageOffset':123},
                        {'imageIndex':1},{'symbol':'first_available_symbol'},{'symbol':'PRIVATE_CANARY'}]}])
        self.scan();self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sent[0][1]['first_symbol'],'first_available_symbol')

    def test_legacy_crash_format(self):
        for i in range(2):
            text='''Process: Private [123]
Path: /Library/Developer/CoreSimulator/Devices/opaque/data/Test.app/Test
Identifier: org.examforge.TealDarwin
Date/Time: %s
Exception Type: EXC_CRASH (SIGABRT)
Crashed Thread: 1
Thread 0:
0 other 0x123 PRIVATE_CANARY + 2
Thread 1 Crashed:
0 libsystem 0x123 __pthread_kill + 8
1 private 0x456 PRIVATE_CANARY + 4
''' % datetime.fromtimestamp(self.now-i,timezone.utc).strftime('%Y-%m-%d %H:%M:%S +0000')
            p=self.reports/(str(i)+'.crash');p.write_text(text);os.utime(p,(self.now-i,self.now-i))
        self.scan();self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sent[0][1]['first_symbol'],'__pthread_kill')
        self.assertNotIn('PRIVATE_CANARY',json.dumps(self.sent))

    def test_formal_sender_gets_only_allowlisted_body(self):
        import sys
        from types import SimpleNamespace
        fields=dict(bundle_id='org.examforge.TealDarwin',count=2,times=['2026-11-07T00:00:00+00:00']*2,
                    exception='EXC_CRASH',first_symbol='__pthread_kill')
        calls=[]
        fake=SimpleNamespace(send_server=lambda payload:(calls.append(payload) or {'id':123}),sent_id=lambda result:result.get('id'))
        with patch.dict(sys.modules,agentstack_stallself=fake):self.mod.notify('ProudTuring',fields)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['seat'],'ProudTuring')
        self.assertTrue(calls[0]['subject'].startswith('[blocked]'))
        body=json.loads(calls[0]['body_md']);self.assertEqual(body,fields)


if __name__=='__main__':unittest.main(verbosity=2)
