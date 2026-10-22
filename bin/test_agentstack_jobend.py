import copy
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('jobend', Path(__file__).with_name('agentstack_jobend.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def proc(pid, parent, args, started='Mon Oct 19 21:00:00 2026', tty='ttys026'):
    return dict(pid=pid, ppid=parent, args=args, started=started, tty=tty,
                key=str(pid) + ':' + started)


PANES = [dict(seat='SwiftDarwin', pid=100, tty='ttys026')]
BASE = {100: proc(100, 1, '/bin/zsh'), 101: proc(101, 100, 'node codex')}
JOB = proc(200, 101, '/bin/sh /tmp/scripts/heavy_job_lock.sh test-heavy -- sleep 8')
NO_LOGS = lambda pid: []


class JobEndTests(unittest.TestCase):
    def step(self, state, rows, panes=PANES):
        return m.advance(state, rows, panes, now=1000, log_finder=NO_LOGS)

    def test_required_three_dry_runs(self):
        results = []
        for label, initial, final, expected in [
            ('ended', dict(BASE, **{}), BASE, 1),
            ('continues', dict(BASE, **{}), None, 0),
            ('sleep-only', dict(BASE, **{}), BASE, 0),
        ]:
            state = {}
            initial[200] = JOB if label != 'sleep-only' else proc(200, 101, 'sleep 8')
            self.assertEqual(self.step(state, initial), [])
            events = self.step(state, initial if final is None else final)
            self.assertEqual(len(events), expected)
            self.assertEqual(self.step(state, BASE), [] if label != 'continues' else [state['events'][next(iter(state['events']))]])
            if events:
                self.assertEqual(events[0]['seat'], 'SwiftDarwin')
            results.append(dict(case=label, notification_count=len(events), expected=expected))
        print('REQUIRED_DRY_RUNS ' + json.dumps(results))

    def test_duplicate_sweeps_and_restart_send_once(self):
        state = {}
        self.step(state, {**BASE, 200: JOB})
        self.step(state, BASE)
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            m.notify_pending(state, path, lambda job: calls.append(job['id']) or dict(id=1))
            state = json.loads(path.read_text())
            self.step(state, BASE)
            m.notify_pending(state, path, lambda job: calls.append(job['id']))
        self.assertEqual(len(calls), 1)

    def test_lost_response_does_not_duplicate(self):
        state = {}
        self.step(state, {**BASE, 200: JOB})
        self.step(state, BASE)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            sender = mock.Mock(side_effect=TimeoutError('private detail must not persist'))
            m.notify_pending(state, path, sender)
            self.assertNotIn('private detail', path.read_text())
            m.notify_pending(json.loads(path.read_text()), path, sender)
            self.assertEqual(sender.call_count, 1)
            self.assertEqual(next(iter(state['events'].values()))['status'], 'delivery_uncertain')

    def test_sending_claim_is_durable_before_transport(self):
        state = {}
        self.step(state, {**BASE, 200: JOB})
        self.step(state, BASE)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            def sender(job):
                self.assertEqual(next(iter(json.loads(path.read_text())['events'].values()))['status'], 'sending')
                return dict(id=42)
            m.notify_pending(state, path, sender)

    def test_wrapper_and_xcode_are_one_job(self):
        state = {}
        self.step(state, {**BASE, 200: JOB, 201: proc(201, 200, '/usr/bin/xcodebuild test')})
        self.assertEqual(len(state['active']), 1)
        self.assertEqual(self.step(state, {**BASE, 200: JOB}), [])
        self.assertEqual(len(self.step(state, BASE)), 1)

    def test_surviving_orphan_xcode_delays_notification(self):
        state = {}
        self.step(state, {**BASE, 200: JOB, 201: proc(201, 200, 'xcodebuild test')})
        self.assertEqual(self.step(state, {**BASE, 201: proc(201, 1, 'xcodebuild test', tty='??')}), [])
        self.assertEqual(len(self.step(state, BASE)), 1)

    def test_tracked_setsid_job_retains_owner(self):
        state = {}
        self.step(state, {**BASE, 200: JOB})
        detached = dict(JOB, ppid=1, tty='??')
        self.assertEqual(self.step(state, {**BASE, 200: detached}), [])
        self.assertEqual(self.step(state, BASE)[0]['seat'], 'SwiftDarwin')

    def test_nohup_terminal_owner_fallback(self):
        state = {}
        self.step(state, {**BASE, 200: dict(JOB, ppid=1)})
        self.assertEqual(len(self.step(state, BASE)), 1)

    def test_unobserved_detached_without_terminal_is_not_misattributed(self):
        state = {}
        self.step(state, {**BASE, 200: dict(JOB, ppid=1, tty='??')})
        self.assertEqual(state['active'], {})

    def test_simctl_and_sleep_never_register(self):
        state = {}
        self.step(state, {**BASE, 200: proc(200, 101, 'sleep 50'), 201: proc(201, 101, '/usr/bin/xcrun simctl list')})
        self.assertEqual(self.step(state, BASE), [])

    def test_program_position_and_prompt_false_positives(self):
        for args in ['codex --prompt xcodebuild heavy_job_lock.sh sleep',
                     'node script.js heavy_job_lock.sh', 'echo xcodebuild',
                     '/bin/sh -c "echo heavy_job_lock.sh"',
                     '/bin/zsh -lc "xcodebuild test"', 'not-xcodebuild test',
                     'python3 probe.py /tmp/heavy_job_lock.sh']:
            with self.subTest(args=args):
                self.assertIsNone(m.command_kind(args))
        for args in ['xcodebuild test', '/usr/bin/xcodebuild build-for-testing',
                     '/usr/bin/xcrun xcodebuild test',
                     '/bin/sh -eu /tmp/heavy_job_lock.sh lane -- sleep 1',
                     '/tmp/heavy_job_lock.sh lane -- xcodebuild test']:
            with self.subTest(args=args):
                self.assertIsNotNone(m.command_kind(args))

    def test_pid_reuse_is_a_distinct_job(self):
        state = {}
        self.step(state, {**BASE, 200: JOB})
        new = proc(200, 101, JOB['args'], started='Mon Oct 19 21:10:00 2026')
        first = self.step(state, {**BASE, 200: new})
        self.assertEqual(len(first), 1)
        second = self.step(state, BASE)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0]['id'], second[0]['id'])

    def test_two_seats_ownership(self):
        state = {}
        panes = PANES + [dict(seat='OtherSeat', pid=300, tty='ttys030')]
        rows = {**BASE, 200: JOB, 300: proc(300, 1, 'sh', tty='ttys030'),
                301: proc(301, 300, 'xcodebuild test', tty='ttys030')}
        self.step(state, rows, panes)
        self.assertEqual({j['seat'] for j in self.step(state, BASE, panes)}, {'SwiftDarwin', 'OtherSeat'})

    def test_command_does_not_store_sensitive_argv(self):
        kind = m.command_kind('xcodebuild test SECRET_TOKEN=private --data /private/file')
        self.assertEqual(kind['excerpt'], 'xcodebuild test')
        kind = m.command_kind('codex ' + 'a' * 1000000 + ' xcodebuild')
        self.assertIsNone(kind)

    def test_log_exit_is_new_and_matching_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'job.log'
            path.write_text('traffic: [test-heavy] done (exit 99)\n')
            offset = path.stat().st_size
            job = dict(kind='heavy_job_lock', label='test-heavy', logs=[dict(path=str(path), offset=offset)])
            self.assertIsNone(m.finished_exit(job))
            with path.open('a') as out:
                out.write('traffic: [other] done (exit 55)\ntraffic: [test-heavy] done (exit 1)\n')
            self.assertEqual(m.finished_exit(job), 1)

    def test_nonterminal_tmux_metadata_preserves_fields(self):
        # Actual clean-launchd tmux turns control-tab delimiters into underscores.
        def render(command):
            return command[-1].replace('#{session_name}', 'SwiftDarwin').replace('#{pane_pid}', '100').replace('#{pane_tty}', '/dev/ttys026').replace('\t', '_') + '\n'
        with mock.patch.object(m, 'execute', side_effect=render):
            self.assertEqual(m.pane_snapshot(), PANES)

    def test_ps_start_time_and_malformed_snapshot(self):
        rows = m.parse_processes('200 101 ttys026 Mon Oct 19 21:00:00 2026 /bin/sh /tmp/heavy_job_lock.sh demo -- sleep 1\n')
        self.assertEqual(rows[200]['key'], JOB['key'])
        for bad in ['', 'not a process\n']:
            with self.assertRaises(ValueError):
                m.parse_processes(bad)

    def test_dry_run_does_not_consume_real_delivery_state(self):
        state = {}
        self.step(state, {**BASE, 200: JOB})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            path.write_text(json.dumps(state))
            before = path.read_bytes()
            with mock.patch.object(m, 'process_snapshot', return_value=BASE), \
                 mock.patch.object(m, 'pane_snapshot', return_value=PANES), \
                 mock.patch.object(m, 'send_server') as sender:
                events = m.sweep(path, dry_run=True)
            self.assertEqual(len(events), 1)
            sender.assert_not_called()
            self.assertEqual(path.read_bytes(), before)

    def test_legacy_head_alerts_and_original_main_body_preserved(self):
        here = Path(__file__).parent
        baseline = here / 'before-watch.py.txt'
        if not baseline.exists():
            baseline = here / 'agentstack-seat-stall-watch.py.bak-20261020-jobend'
        def functions(path):
            tree = ast.parse(path.read_text())
            return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        old = functions(baseline)
        new = functions(here / 'agentstack-seat-stall-watch.py')
        for name in ['send', 'send_approval', 'descendants']:
            self.assertEqual(ast.dump(old[name]), ast.dump(new[name]))
        # OPS-STALL-SELF-1 adds one self hook/dry-run diagnostics and makes the
        # existing final state write atomic. All original head branches remain.
        class StripSelfHook(ast.NodeTransformer):
            def visit_Expr(self, node):
                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id in {'notify_self', 'dry_skip'}:
                    return None
                return self.generic_visit(node)
        normalized = StripSelfHook().visit(copy.deepcopy(new['main']))
        final = normalized.body[-1]
        self.assertIsInstance(final, ast.If)
        self.assertEqual(ast.dump(final.test), ast.dump(ast.parse('not DRYRUN', mode='eval').body))
        self.assertEqual(final.body[0].value.func.id, 'save_state')
        normalized.body[-1] = old['main'].body[-1]
        self.assertEqual([ast.dump(n) for n in old['main'].body],
                         [ast.dump(n) for n in normalized.body[2:]])


if __name__ == '__main__':
    unittest.main(verbosity=2)
