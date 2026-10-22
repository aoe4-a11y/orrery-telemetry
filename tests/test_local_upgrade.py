"""Behavioral checks for local fleet contracts preserved across the upgrade."""
import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest
from dashboard import codex_models

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_r062_default_and_explicit_authorization(monkeypatch, tmp_path):
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    monkeypatch.delenv('AGENTSTACK_CODEX_MODELS', raising=False)
    monkeypatch.delenv('AGENTSTACK_ALLOW_XHIGH', raising=False)
    assert codex_models.resolve_effort('gpt-6.1-sol') == 'medium'
    assert codex_models.resolve_effort('gpt-6.1-sol', 'high') == 'high'
    for effort in ['xhigh', 'max', 'ultra']:
        with pytest.raises(ValueError, match='R-062'):
            codex_models.resolve_effort('gpt-6.1-sol', effort)
    monkeypatch.setenv('AGENTSTACK_ALLOW_XHIGH', '1')
    assert codex_models.resolve_effort('gpt-6.1-sol', 'xhigh') == 'xhigh'


def test_fleet_picker_has_no_hyphen():
    result = subprocess.run(['/bin/bash', '-c',
        'source "$1"; ags_pick_adjective_scientist_name', 'test',
        str(ROOT / 'bin/lib/agentstack-scientists.sh')], capture_output=True, text=True, check=True)
    assert '-' not in result.stdout.strip()
    assert result.stdout.strip()


def test_child_home_rekeys_persisted_hooks_trust(tmp_path):
    spec = importlib.util.spec_from_file_location('upgrade_child_resume', ROOT / 'hooks/child_resume.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    source = tmp_path/'source'; source.mkdir()
    home = tmp_path/'runtime/child-agents/SunnyCurie.codex-home'
    (source/'hooks.json').write_text('{}')
    (source/'config.toml').write_text('[hooks.state."'+str(source)+'/hooks.json:abc"]\ntrusted = true\n')
    runner = tmp_path/'runner';runner.write_text('#!/bin/sh\n');runner.chmod(0o700)
    token = tmp_path/'credential';token.write_text('isolated-test-credential');token.chmod(0o600)
    module.build_home(home=home, source=source, runner=runner, child='SunnyCurie',
        project_key=str(tmp_path), token_file=token, mcp_url='http://127.0.0.1:1/mcp',
        mail_env='', runtime_dir=tmp_path/'runtime', bearer_mode='none', python_bin=sys.executable,
        mcp_profile='inherit')
    generated = (home/'config.toml').read_text()
    assert str(home)+'/hooks.json:abc' in generated
    assert str(source)+'/hooks.json:abc' not in generated


def test_rollback_preserves_new_mail_state_and_restores_payload(tmp_path):
    spec = importlib.util.spec_from_file_location('upgrade_backup', ROOT / 'scripts/fleet-upgrade-backup.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    home=tmp_path/'home';live=home/'.agentstack';(live/'bin').mkdir(parents=True)
    (live/'bin/tool').write_text('old');(live/'bin/tool').chmod(0o755)
    (live/'config').mkdir();(live/'config/head-send-lint.json').write_text('{"threshold":1}')
    (live/'mail').mkdir();(live/'mail/storage.sqlite3').write_text('initial-mail')
    (live/'runtime').mkdir();(live/'runtime/agent_token_SunnyCurie').write_text('synthetic-secret')
    project=home/'project';project.mkdir();(project/'CLAUDE.md').write_text('old-managed-doc')
    snapshot=tmp_path/'snapshot'
    module.snapshot(home,snapshot,project)
    assert not (snapshot/'files/.agentstack/mail').exists()
    assert not (snapshot/'files/.agentstack/runtime').exists()
    (live/'bin/tool').write_text('new');(live/'mail/storage.sqlite3').write_text('new-mail')
    (live/'config/head-send-lint.json').write_text('{"threshold":2}')
    (project/'CLAUDE.md').write_text('new-managed-doc')
    module.restore(home,snapshot)
    assert (live/'bin/tool').read_text()=='old'
    assert (live/'config/head-send-lint.json').read_text()=='{"threshold":1}'
    assert (live/'bin/tool').stat().st_mode&0o777==0o755
    assert (live/'mail/storage.sqlite3').read_text()=='new-mail'
    assert (live/'runtime/agent_token_SunnyCurie').read_text()=='synthetic-secret'
    assert (project/'CLAUDE.md').read_text()=='old-managed-doc'


def test_restart_rejects_project_mismatch_before_stopping_current_seat(tmp_path):
    import json,shutil
    home=tmp_path/'home';stack=home/'.agentstack';runtime=stack/'runtime';runtime.mkdir(parents=True)
    hooks=stack/'hooks';hooks.mkdir();shutil.copy2(ROOT/'hooks/seat_lifecycle.py',hooks/'seat_lifecycle.py')
    token=runtime/'agent_token_SunnyCurie';token.write_text('fixture-owner');token.chmod(0o600)
    state=runtime/'child-agents/SunnyCurie.json';state.parent.mkdir();state.write_text(json.dumps({'agent_name':'SunnyCurie','project_key':'/authoritative/project','registration_token':'fixture-owner'}));state.chmod(0o600)
    before=state.read_bytes();task=tmp_path/'task.md';task.write_text('# fixture task')
    trace=tmp_path/'trace';fake=tmp_path/'fake';fake.mkdir();tmux=fake/'tmux';tmux.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$TRACE"\nexit 0\n');tmux.chmod(0o755)
    env={k:v for k,v in os.environ.items() if not k.startswith('AGENTSTACK_')}
    env.update(HOME=str(home),TRACE=str(trace),PATH=str(fake)+':'+os.environ['PATH'],AGENTSTACK_PROJECT_KEY=str(tmp_path))
    run=subprocess.run(['/bin/bash',str(ROOT/'bin/agentstack-restart-seat'),'SunnyCurie',str(task),'gpt-6.1-sol','medium',str(tmp_path)],env=env,capture_output=True,text=True)
    assert run.returncode!=0 and 'project mismatch' in run.stderr
    assert not trace.exists()
    assert token.read_text()=='fixture-owner' and state.read_bytes()==before


def test_modern_launch_and_resume_honor_the_fork_sandbox_override(monkeypatch):
    from dashboard import server
    monkeypatch.setenv('AGENTSTACK_CODEX_SANDBOX','danger-full-access')
    assert '--sandbox danger-full-access' in server._codex_child_launch_flags([])
    monkeypatch.delenv('AGENTSTACK_CODEX_SANDBOX')
    assert '--sandbox workspace-write' in server._codex_child_launch_flags([])


def test_r062_menu_and_cached_default_use_permitted_efforts(monkeypatch):
    monkeypatch.delenv('AGENTSTACK_ALLOW_XHIGH', raising=False)
    policy = codex_models.EffortPolicy(('low', 'medium', 'high', 'xhigh'), 'xhigh')
    catalog = codex_models.ModelCatalog(('gpt-test',), 'fixture', {'gpt-test': policy})
    monkeypatch.setattr(codex_models, 'resolve_catalog', lambda *a, **k: catalog)
    assert codex_models.resolve_effort('gpt-test') == 'medium'
    menu = codex_models.provider_catalog()
    assert menu['model_efforts']['gpt-test'] == ['low', 'medium', 'high']
    assert menu['model_effort_defaults']['gpt-test'] == 'medium'
