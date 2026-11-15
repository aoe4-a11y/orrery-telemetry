import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import agentstack_stallself as m


class StallSelfTests(unittest.TestCase):
    def test_terminal_forms_and_nonterminal_forms(self):
        terminal = ['[receipt] done', '[blocked] waiting', '[env-blocked] deny',
                    '[terminal] done', '[closed] end', '/closed] end', '[done] end',
                    'Re: [receipt] done', ' Re: Re: [blocked] wait', 'RE: /closed] end']
        active = ['[progress] next', '[plan] next', '[station] task', '[ack] read',
                  'Re: [progress] next', 'a [receipt] inside', '']
        for subject in terminal:
            with self.subTest(subject=subject):
                self.assertTrue(m.terminal_subject(subject))
        for subject in active:
            with self.subTest(subject=subject):
                self.assertFalse(m.terminal_subject(subject))
        self.assertEqual(m.decision(None), (False, 'no_outgoing'))
        self.assertEqual(m.decision(dict(subject='[progress] next'), True), (False, 'ignored'))

    def make_db(self, p):
        with sqlite3.connect(p) as c:
            c.executescript('CREATE TABLE agents(id INTEGER,name TEXT);'
                            'CREATE TABLE messages(id INTEGER,project_id INTEGER,sender_id INTEGER,'
                            'subject TEXT,created_ts TEXT,body_md TEXT);')
            c.executemany('INSERT INTO agents VALUES (?,?)', [(1,'Seat'),(2,'Other')])
            c.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?)', [
                (100,1,1,'[progress] old','2026-10-20 01:00:00','not read'),
                (5,1,1,'[receipt] newer','2026-10-20T02:00:00+00:00','not read'),
                (999,2,1,'wrong project','2026-10-20 03:00:00','not read'),
                (1000,1,2,'wrong sender','2026-10-20 03:00:00','not read')])
        c.close()

    def test_latest_sender_all_recipients_and_time_cutoff(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'messages.sqlite';self.make_db(p)
            self.assertEqual(m.last_outgoing('Seat',db=p)['id'],5)
            self.assertEqual(m.last_outgoing('Seat','2026-10-20T01:30:00Z',db=p)['id'],100)
            self.assertIsNone(m.last_outgoing('Never',db=p))
            self.assertEqual(set(m.last_outgoing('Seat',db=p)), {'id','subject','created_ts'})

    def test_missing_db_not_created(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'absent.sqlite'
            with self.assertRaises(sqlite3.OperationalError):m.last_outgoing('Seat',db=p)
            self.assertFalse(p.exists())

    def test_body_and_exact_recipient(self):
        v=m.notice('Seat',35,'line\nnext',dict(id=42,subject='[plan] one\ntwo'))
        self.assertEqual(v['seat'],'Seat');self.assertEqual(len(v['body_md'].splitlines()),4)
        self.assertIn('id=42',v['body_md']);self.assertIn('M-037',v['body_md'])
        self.assertIn('自分の入力が要らない工程は続ける',v['body_md'])
        self.assertTrue(v['subject'].startswith('[progress] 席の見張り: 画面が 35 分'))

    def sample(self):return {'Seat':dict(hash='screen',since=0,alerted=False)}
    def latest(self,_):return dict(id=7,subject='[progress] next',created_ts='2026-10-20 01:00:00')

    def test_claim_durable_before_send_and_restart_once(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'state.json';state=self.sample();calls=[];logs=[]
            def sender(payload):
                self.assertEqual(json.loads(path.read_text())['Seat']['self_notice']['status'],'sending')
                calls.append(payload);return dict(deliveries=[dict(payload=dict(id=81))])
            self.assertEqual(m.notify_self(state,path,'Seat',31,'ready',reader=self.latest,sender=sender,logger=logs.append),'sent')
            reloaded=json.loads(path.read_text())
            self.assertEqual(m.notify_self(reloaded,path,'Seat',36,'ready',reader=self.latest,sender=sender),'already_claimed')
            self.assertEqual(len(calls),1);self.assertIn('seat=Seat last=7 sent=81 count=1',logs[0])

    def test_lost_reply_never_resends_or_leaks_error(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'state.json';state=self.sample();sender=mock.Mock(side_effect=TimeoutError('secret detail'))
            self.assertEqual(m.notify_self(state,path,'Seat',31,'ready',reader=self.latest,sender=sender),'delivery_uncertain')
            m.notify_self(json.loads(path.read_text()),path,'Seat',31,'ready',reader=self.latest,sender=sender)
            self.assertEqual(sender.call_count,1);self.assertNotIn('secret detail',path.read_text())

    def test_rearm_when_watcher_replaces_screen_entry(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'state.json';state=self.sample();sender=mock.Mock(return_value=dict(id=11))
            m.notify_self(state,p,'Seat',31,'ready',reader=self.latest,sender=sender)
            state['Seat']=dict(hash='changed-screen',since=0,alerted=False)
            m.notify_self(state,p,'Seat',31,'ready',reader=self.latest,sender=sender)
            self.assertEqual(sender.call_count,2)

    def test_terminal_none_and_read_error_never_send(self):
        for value in [None,dict(id=7,subject='Re: [receipt] done')]:
            state=self.sample();sender=mock.Mock()
            m.notify_self(state,Path('/unused'),'Seat',31,'tail',reader=lambda _:value,sender=sender)
            sender.assert_not_called();self.assertNotIn('self_notice',state['Seat'])
        sender=mock.Mock();m.notify_self(self.sample(),Path('/unused'),'Seat',31,'tail',reader=mock.Mock(side_effect=OSError('private')),sender=sender)
        sender.assert_not_called()

    def test_dryrun_shows_send_skip_and_never_persists(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'state.json';p.write_text(json.dumps(self.sample()));before=p.read_bytes();sender=mock.Mock()
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                m.notify_self(self.sample(),p,'Seat',31,'ready',dry_run=True,reader=self.latest,sender=sender)
                m.notify_self(self.sample(),p,'Seat',31,'ready',dry_run=True,reader=lambda _:None,sender=sender)
            self.assertIn('DRYRUN self send seat=Seat',output.getvalue());self.assertIn('DRYRUN self skip seat=Seat',output.getvalue());self.assertEqual(p.read_bytes(),before);sender.assert_not_called()

    def test_legacy_python_handoff(self):
        result=mock.Mock(returncode=0,stdout='{"id": 99}')
        with mock.patch.object(m.sys,'version_info',(3,9)), mock.patch.object(m.subprocess,'run',return_value=result) as proc:
            self.assertEqual(m.send_server(dict(seat='Seat')),dict(id=99))
        self.assertEqual(proc.call_args.args[0][0],'/opt/homebrew/bin/python3')
        self.assertEqual(proc.call_args.args[0][-1],'--send-notice')

    def test_canonical_sender_normal_to_seat_only(self):
        sys.path.insert(0,str(m.HOME/'integrations/codex_app/src'))
        import agentstack_codex_app.agent_mail_client as clientmod
        payload=m.notice('Seat',31,'ready',self.latest('Seat'))
        with mock.patch.object(m.subprocess,'run',return_value=mock.Mock(returncode=0,stdout='unit-test-credential')), mock.patch.object(clientmod,'AgentMailClient',autospec=True) as client:
            m.send_server(payload)
        kwargs=client.return_value.send_message.call_args.kwargs
        self.assertEqual(kwargs['to'],['Seat']);self.assertEqual(kwargs['agent_name'],'KindPasteur');self.assertEqual(kwargs['importance'],'normal');self.assertNotIn('cc',kwargs)


# Functional integration of the existing alert branch (no real mail/pane calls).
class WatcherIntegrationTests(unittest.TestCase):
    def load_watcher(self):
        spec=importlib.util.spec_from_file_location('seat_watch',Path(__file__).with_name('agentstack-seat-stall-watch.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def setup_watch(self,tmp,dry=False,ignored=False):
        import hashlib,time
        watch=self.load_watcher();watch.STATE=str(Path(tmp)/'state.json');watch.IGNORE=str(Path(tmp)/'ignore.txt');watch.LOG=str(Path(tmp)/'watch.log');watch.DRYRUN=dry
        Path(watch.IGNORE).write_text('Seat\n' if ignored else '')
        state={'Seat':dict(hash=hashlib.sha256(b'ready').hexdigest(),since=time.time()-3600,alerted=False)}
        Path(watch.STATE).write_text(json.dumps(state));db=Path(tmp)/'names.sqlite'
        with sqlite3.connect(db) as con:con.execute('CREATE TABLE agents(name TEXT)');con.execute('INSERT INTO agents VALUES ("Seat")')
        con.close()
        original_connect=sqlite3.connect
        def census(*args,**kwargs):return original_connect(db)
        def run(*args):
            if args[1]=='list-sessions':return 'Seat\n'
            if args[1]=='capture-pane':return 'ready'
            if args[1]=='list-panes':return '100\n'
            raise AssertionError('unexpected command')
        return watch,census,run

    def test_head_notice_kept_and_self_once_across_watch_restart(self):
        import agentstack_jobend
        with tempfile.TemporaryDirectory() as tmp:
            watch,db,run=self.setup_watch(tmp);calls=[]
            def hook(*args,**kwargs):return m.notify_self(*args,**kwargs,reader=lambda _:dict(id=2,subject='[plan] next'),sender=lambda v:calls.append(v) or dict(id=3))
            with mock.patch.object(watch.sqlite3,'connect',side_effect=db),mock.patch.object(watch,'run',side_effect=run),mock.patch.object(watch,'descendants',return_value=[]),mock.patch.object(watch,'send') as head,mock.patch.object(watch,'notify_self',side_effect=hook),mock.patch.object(agentstack_jobend,'sweep',return_value=[]):
                watch.main();watch.main()
            self.assertEqual(head.call_count,1);self.assertEqual(len(calls),1)
            self.assertEqual(json.loads(Path(watch.STATE).read_text())['Seat']['self_notice']['sent_message_id'],3)

    def test_ignored_seat_gets_neither_notification(self):
        import agentstack_jobend
        with tempfile.TemporaryDirectory() as tmp:
            watch,db,run=self.setup_watch(tmp,ignored=True)
            with mock.patch.object(watch.sqlite3,'connect',side_effect=db),mock.patch.object(watch,'run',side_effect=run),mock.patch.object(watch,'send') as head,mock.patch.object(watch,'notify_self') as own,mock.patch.object(agentstack_jobend,'sweep',return_value=[]):watch.main()
            head.assert_not_called();own.assert_not_called()

    def test_watcher_dryrun_does_not_consume_alert_or_self_claim(self):
        import agentstack_jobend
        with tempfile.TemporaryDirectory() as tmp:
            watch,db,run=self.setup_watch(tmp,dry=True);before=Path(watch.STATE).read_bytes();output=io.StringIO()
            def hook(*args,**kwargs):return m.notify_self(*args,**kwargs,reader=lambda _:dict(id=2,subject='[plan] next'),sender=mock.Mock(side_effect=AssertionError('must not send')))
            with mock.patch.object(watch.sqlite3,'connect',side_effect=db),mock.patch.object(watch,'run',side_effect=run),mock.patch.object(watch,'descendants',return_value=[]),mock.patch.object(watch,'send') as head,mock.patch.object(watch,'notify_self',side_effect=hook),mock.patch.object(agentstack_jobend,'sweep',return_value=[]),contextlib.redirect_stdout(output):watch.main()
            head.assert_not_called();self.assertEqual(Path(watch.STATE).read_bytes(),before);self.assertIn('DRYRUN self send seat=Seat',output.getvalue())

    def test_concurrent_guard_does_not_run_second_watcher(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            watch,_,_=self.setup_watch(tmp)
            with open(watch.STATE+'.lock','a') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with mock.patch.object(watch,'main') as main:watch.guarded_main()
            main.assert_not_called()



class ReplayTests(unittest.TestCase):
    def test_at_alert_time_and_cutoff(self):
        spec=importlib.util.spec_from_file_location('stall_replay',Path(__file__).with_name('agentstack-stallself-replay.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);db=root/'messages.sqlite';StallSelfTests().make_db(db)
            log=root/'watch.log';log.write_text('[2026-10-20 10:30:00] alert Seat unchanged 35 min\n[2026-10-20 11:30:00] alert Seat unchanged 40 min\n[2026-10-20 13:00:00] alert Seat unchanged 40 min\n');ignore=root/'ignore.txt';ignore.write_text('')
            report=module.replay(log,'2026-10-20','2026-10-20T03:00:00Z',ignore,db=db)
            self.assertEqual((report['alert_count'],report['would_send'],report['would_not_send']),(2,1,1));self.assertEqual([x['last_outgoing']['id'] for x in report['rows']],[100,5]);self.assertEqual(report['sent_messages'],0)

    def test_replay_current_ignore_explicit_and_readonly(self):
        spec=importlib.util.spec_from_file_location('stall_replay',Path(__file__).with_name('agentstack-stallself-replay.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);db=root/'messages.sqlite';StallSelfTests().make_db(db);before=db.read_bytes()
            log=root/'watch.log';log.write_text('[2026-10-20 10:30:00] alert Seat unchanged 35 min\n');ignore=root/'ignore.txt';ignore.write_text('Seat # held\n')
            report=module.replay(log,'2026-10-20','2026-10-20T03:00:00Z',ignore,db=db)
            self.assertEqual(report['would_not_send'],1);self.assertEqual(report['rows'][0]['reason'],'ignored');self.assertIn('historical membership unmeasured',report['ignore_scope']);self.assertEqual(db.read_bytes(),before)


if __name__=='__main__':unittest.main(verbosity=2)
