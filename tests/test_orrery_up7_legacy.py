"""Legacy child-home behavior with isolated synthetic configuration."""
import os
import json
import shlex
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
RELEASE=ROOT/'fleet/releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595/hooks'

class LegacyChildHomeTest(unittest.TestCase):
    def test_watcher_does_not_inject_into_head_panes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);trace=root/'trace';source=(ROOT/'hooks/watch_agent_mail_signals.sh').read_text()
            start=source.index('deliver_worker() {');end=source.index('\nprocess_existing_signals()',start)
            shell='''state_mark_result() { printf 'mark:%s\\n' "$3" >> "$TRACE"; }
release_delivery_lease() { printf 'release\\n' >> "$TRACE"; }
tmux() { printf 'unexpected-tmux\\n' >> "$TRACE"; return 77; }
'''+source[start:end]+'''\ndeliver_worker /fixture/signal ProudTuring 1 Sender '[receipt] fixture' normal 0
deliver_worker /fixture/signal PinkTesla 2 Sender '[receipt] fixture' normal 0
'''
            run=subprocess.run(['/bin/bash','-c',shell],env={'HOME':str(root),'PATH':'/usr/bin:/bin','TRACE':str(trace)},
                               capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(trace.read_text().splitlines(),['mark:head_no_pane','release','mark:head_no_pane','release'])

    def test_check_seats_classifies_fake_panes_without_live_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);fake=root/'fake';fake.mkdir();project=root/'project';project.mkdir()
            def executable(path,text):path.write_text(text);path.chmod(0o755)
            executable(fake/'tmux','#!/bin/bash\nproject='+shlex.quote(str(project))+'\n'+'''
case "$1" in
  list-sessions) printf 'Work\\nGone\\n';;
  capture-pane) case "$*" in *Work*) printf 'Working (esc to interrupt)\\ngpt-6.1-sol high\\n';; *) printf 'invalid cwd\\n';; esac;;
  display-message) case "$*" in *pane_current_path*Work*|*Work*pane_current_path*) printf '%s\\n' "$project";; esac;;
esac
''')
            executable(fake/'sqlite3','#!/bin/sh\nexit 0\n')
            executable(fake/'pgrep','#!/bin/sh\nexit 1\n')
            run=subprocess.run(['/bin/bash',str(ROOT/'bin/agentstack-check-seats')],
                env={'HOME':str(root),'PATH':str(fake)+':/usr/bin:/bin'},capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr)
            rows=run.stdout.splitlines()
            self.assertTrue(any('Work' in row and 'WORKING' in row for row in rows))
            self.assertTrue(any('Gone' in row and 'DEAD-CWD' in row for row in rows))

    def test_spawn_codex_uses_actual_legacy_launch_with_fake_tmux(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);home=root/'home';stack=home/'.agentstack';runtime=stack/'runtime'
            (runtime/'child-agents').mkdir(parents=True);(stack/'bin/lib').mkdir(parents=True)
            fake=root/'fake';fake.mkdir();trace=root/'tmux-trace';project=root/'project';project.mkdir()
            task=root/'task.md';task.write_text('# Synthetic task\n')
            def executable(path,text): path.write_text(text);path.chmod(0o755)
            executable(stack/'bin/agentstack-memory-budget','#!/bin/sh\nexit 0\n')
            subprocess.run(['/bin/cp','-c',str(ROOT/'bin/lib/agentstack-child-name.sh'),str(stack/'bin/lib/agentstack-child-name.sh')],check=True)
            executable(stack/'bin/agentstack-preregister-child', '''#!/bin/bash
while (($#)); do if [[ "$1" == --token-file-out ]]; then token="$2"; shift 2; else shift; fi; done
python3 - "$token" "$AGENTSTACK_RUNTIME_DIR" "$AGENTSTACK_PROJECT_KEY" "$AGENTSTACK_LIFECYCLE_HOOKS_DIR" <<'PY'
import pathlib,sys
token,runtime,project,hooks=sys.argv[1:];sys.path.insert(0,hooks)
from seat_lifecycle import bind_handoff
p=pathlib.Path(token);p.write_text('synthetic');p.chmod(0o600)
bind_handoff(pathlib.Path(runtime),p,'SunnyCurie',project)
PY
echo SunnyCurie
''')
            executable(fake/'sleep','#!/bin/sh\nexit 0\n')
            for command in ('open','osascript','launchctl','pkill','killall'):
                executable(fake/command,'#!/bin/sh\nexit 99\n')
            executable(fake/'tmux','#!/bin/bash\ntrace='+shlex.quote(str(trace))+'\n'+'''
printf '%s\\n' "$*" >> "$trace"
case "$1" in capture-pane) printf 'gpt-6.1-sol medium · /fixture\\n? for shortcuts\\n› \\n';; display-message) printf 'fixture\\n';; esac
exit 0
''')
            env={'HOME':str(home),'PATH':str(fake)+':/usr/bin:/bin:/usr/sbin:/sbin',
                 'AGENTSTACK_HOME':str(stack),'AGENTSTACK_RUNTIME_DIR':str(runtime),
                 'AGENTSTACK_LIFECYCLE_HOOKS_DIR':str(RELEASE),'AGENTSTACK_HOOKS_DIR':str(stack/'hooks'),
                 'AGENTSTACK_PROJECT_KEY':str(project),'PROJECT_KEY':str(project),'PARENT_AGENT':'ParentAgent',
                 'AGENTSTACK_MCP_URL':'http://127.0.0.1:1/mcp','AGENTSTACK_MAIL_HTTP_BEARER_MODE':'disabled',
                 'AGENTSTACK_MCP_PROXY':str(root/'missing'),'AGENTSTACK_TERMINAL':'none',
                 'AGENTSTACK_CODEX_BIN':'/bin/true','AGENTSTACK_AUTO_OPEN_CHILD':'0'}
            run=subprocess.run(['/bin/bash',str(ROOT/'bin/agentstack-spawn-codex'),
                'gpt-6.1-sol',str(task),str(project),'Synthetic task','high'],env=env,text=True,capture_output=True,timeout=45)
            self.assertEqual(run.returncode,0,run.stderr[-2000:])
            state=json.loads((runtime/'child-agents/SunnyCurie.json').read_text())
            self.assertEqual(state['agent_name'],'SunnyCurie')
            self.assertEqual(state['project_key'],str(project))
            commands=trace.read_text()
            self.assertTrue('new-session' in commands, 'new-session was not recorded')
            self.assertTrue('AGENTSTACK_CODEX_MODEL=gpt-6.1-sol' in commands, 'model was not forwarded')
            self.assertTrue('AGENTSTACK_CODEX_EFFORT=high' in commands, 'effort was not forwarded')

    def test_restart_uses_actual_legacy_launch_with_fake_tmux(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);home=root/'home';stack=home/'.agentstack';runtime=stack/'runtime'
            (runtime/'child-agents').mkdir(parents=True);(stack/'bin').mkdir(parents=True)
            fake=root/'fake';fake.mkdir();trace=root/'tmux-trace';project=root/'project';project.mkdir()
            task=root/'task.md';task.write_text('# Synthetic task\n')
            token=runtime/'agent_token_SunnyCurie';token.write_text('synthetic');token.chmod(0o600)
            state=runtime/'child-agents/SunnyCurie.json';state.write_text(json.dumps({'agent_name':'SunnyCurie',
                'project_key':str(project),'registration_token':'synthetic'}));state.chmod(0o600)
            def executable(path,text): path.write_text(text);path.chmod(0o755)
            executable(stack/'bin/agentstack-memory-budget','#!/bin/sh\nexit 0\n')
            executable(fake/'sleep','#!/bin/sh\nexit 0\n')
            for command in ('open','osascript','launchctl','pkill','killall'):
                executable(fake/command,'#!/bin/sh\nexit 99\n')
            executable(fake/'tmux', '#!/bin/bash\ntrace='+shlex.quote(str(trace))+'\n'+'''
printf '%s\\n' "$*" >> "$trace"
case "$1" in
  has-session) exit 1;;
  capture-pane) printf 'gpt-6.1-sol medium · /fixture\\n? for shortcuts\\n› \\n';;
  display-message) printf 'fixture\\n';;
esac
exit 0
''')
            env={'HOME':str(home),'PATH':str(fake)+':/usr/bin:/bin:/usr/sbin:/sbin','TEST_TRACE':str(trace),
                 'AGENTSTACK_HOME':str(stack),'AGENTSTACK_RUNTIME_DIR':str(runtime),
                 'AGENTSTACK_LIFECYCLE_HOOKS_DIR':str(RELEASE),'AGENTSTACK_HOOKS_DIR':str(stack/'hooks'),
                 'AGENTSTACK_PROJECT_KEY':str(project),'PROJECT_KEY':str(project),'PARENT_AGENT':'ParentAgent',
                 'AGENTSTACK_MCP_URL':'http://127.0.0.1:1/mcp','AGENTSTACK_MAIL_HTTP_BEARER_MODE':'disabled',
                 'AGENTSTACK_MCP_PROXY':str(root/'missing'),'AGENTSTACK_TERMINAL':'none',
                 'AGENTSTACK_CODEX_BIN':'/bin/true','AGENTSTACK_AUTO_OPEN_CHILD':'0'}
            run=subprocess.run(['/bin/bash',str(ROOT/'bin/agentstack-restart-seat'),'SunnyCurie',str(task),
                                'gpt-6.1-sol','high',str(project)],env=env,text=True,capture_output=True,timeout=45)
            self.assertEqual(run.returncode,0,run.stderr[-2000:])
            self.assertEqual(json.loads(state.read_text())['agent_name'],'SunnyCurie')
            self.assertEqual(token.read_text(),'synthetic')
            commands=trace.read_text()
            self.assertTrue('new-session' in commands, 'new-session was not recorded')
            self.assertTrue('AGENTSTACK_CODEX_MODEL=gpt-6.1-sol' in commands, 'model was not forwarded')
            self.assertTrue('AGENTSTACK_CODEX_EFFORT=high' in commands, 'effort was not forwarded')

    def test_actual_legacy_child_home_rekeys_hook_trust(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/'codex';source.mkdir();runtime=root/'runtime';runtime.mkdir()
            (source/'hooks.json').write_text('{}')
            (source/'config.toml').write_text('[hooks.state."'+str(source)+'/hooks.json:abc"]\ntrusted = true\n')
            token=root/'synthetic-owner';token.write_text('synthetic');token.chmod(0o600)
            runner=root/'runner';runner.write_text('#!/bin/sh\n');runner.chmod(0o700)
            text=(RELEASE/'spawn_child.sh').read_text(); start=text.index('write_child_codex_home() {')
            end=text.index('\n}\n\n# Generate the direct-spawn',start)+2
            shell=text[start:end]+'\nwrite_child_codex_home SunnyCurie "$TEST_TOKEN"\n'
            env={'HOME':str(root),'PATH':'/usr/bin:/bin','CODEX_HOME':str(source),'RUNTIME_DIR':str(runtime),
                 'AGENTSTACK_RUNTIME_DIR':str(runtime),'AGENTSTACK_LIFECYCLE_HOOKS_DIR':str(RELEASE),
                 'AGENTSTACK_MCP_PROXY':str(runner),'TEST_TOKEN':str(token),'PROJECT_KEY':'/fixture',
                 'MCP_URL':'http://127.0.0.1:1/mcp','MAIL_ENV':'','HTTP_BEARER_MODE':'none'}
            result=subprocess.run(['/bin/bash','-c',shell],env=env,text=True,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            child=runtime/'child-agents/SunnyCurie.codex-home';self.assertEqual(result.stdout.strip(),str(child))
            config=(child/'config.toml').read_text()
            self.assertIn(str(child)+'/hooks.json:abc',config)
            self.assertNotIn(str(source)+'/hooks.json:abc',config)
            self.assertTrue((child/'hooks.json').is_symlink())

if __name__=='__main__':unittest.main()
