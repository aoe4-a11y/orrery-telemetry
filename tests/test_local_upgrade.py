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
    home = tmp_path/'generated'
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
    (live/'mail').mkdir();(live/'mail/storage.sqlite3').write_text('initial-mail')
    (live/'runtime').mkdir();(live/'runtime/agent_token_SunnyCurie').write_text('synthetic-secret')
    project=home/'project';project.mkdir();(project/'CLAUDE.md').write_text('old-managed-doc')
    snapshot=tmp_path/'snapshot'
    module.snapshot(home,snapshot,project)
    assert not (snapshot/'files/.agentstack/mail').exists()
    assert not (snapshot/'files/.agentstack/runtime').exists()
    (live/'bin/tool').write_text('new');(live/'mail/storage.sqlite3').write_text('new-mail')
    (project/'CLAUDE.md').write_text('new-managed-doc')
    module.restore(home,snapshot)
    assert (live/'bin/tool').read_text()=='old'
    assert (live/'bin/tool').stat().st_mode&0o777==0o755
    assert (live/'mail/storage.sqlite3').read_text()=='new-mail'
    assert (live/'runtime/agent_token_SunnyCurie').read_text()=='synthetic-secret'
    assert (project/'CLAUDE.md').read_text()=='old-managed-doc'
