"""Standard spawn contracts, using fixture catalogs and no live runtimes."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dashboard import managed_catalog, server


@pytest.fixture
def catalog(monkeypatch):
    rows = [
        {'id': provider, 'models': [{'id': provider + '-fixture', 'harnesses': [
            {'id': 'dsh', 'available': True, 'efforts': ['low', 'high'],
             'default_effort': 'high', 'effort_source': 'harness'},
            {'id': 'hermes', 'available': True, 'efforts': None,
             'default_effort': None, 'effort_source': 'unknown'},
        ]}]}
        for provider in ('deepseek', 'strata')
    ]
    monkeypatch.setattr(server, '_spawn_catalog_providers', lambda: rows)
    monkeypatch.setattr(server, '_managed_spawn_manager',
                        lambda: pytest.fail('standard spawn entered managed controller'))
    monkeypatch.setattr(server, '_mcp_call', lambda *a, **k: pytest.fail('unexpected registration'))
    return rows


@pytest.fixture
def preview(monkeypatch, tmp_path, catalog):
    launcher = tmp_path / 'spawn_child.sh'
    launcher.write_text('#!/bin/sh\nexit 0\n')
    monkeypatch.setattr(server, 'SPAWN_SCRIPT', str(launcher))
    monkeypatch.setattr(server, '_project_key', lambda: '/fixture/project')
    return {'standalone': True, 'task': 'Original task with no managed prefix',
            'dir': str(tmp_path), 'dry_run': True}


@pytest.mark.parametrize('provider', ['deepseek', 'strata'])
@pytest.mark.parametrize('harness', ['dsh', 'hermes'])
def test_four_pairs_use_standard_launcher_and_unchanged_options(preview, provider, harness):
    result = server.do_spawn({**preview, 'provider': provider, 'harness': harness,
                             'model': provider + '-fixture', 'worktree': True,
                             'worktree_base': 'origin/main', 'headless': False})
    assert result['ok'] and result['dry_run']
    assert result['argv'][5:] == [
        '--standalone', '--harness', harness, '--backend', provider,
        '--model', provider + '-fixture', '--worktree', '--worktree-base', 'origin/main',
        preview['task'], preview['dir'],
    ]
    assert result['effort'] == ''
    assert result['launcher_env'] == {'AGENTSTACK_AUTO_OPEN_CHILD': '1'}
    assert not {'attempt_id', 'managed'} & result.keys()


def test_parent_task_and_explicit_effort_are_standard(preview):
    task = 'The task is passed unchanged'
    result = server.do_spawn({**preview, 'standalone': False, 'parent': 'FixtureParent',
                             'provider': 'deepseek', 'harness': 'dsh',
                             'model': 'deepseek-fixture', 'effort': 'high', 'task': task})
    assert result['ok']
    assert '--standalone' not in result['argv']
    assert result['argv'][5:13] == [
        '--harness', 'dsh', '--backend', 'deepseek', '--model', 'deepseek-fixture', '--effort', 'high']
    assert result['argv'][-2:] == [task, preview['dir']]


@pytest.mark.parametrize('changes', [
    {'harness': None}, {'harness': 'claude-code'}, {'harness': []},
    {'model': 'different-fixture'}, {'model': ''}, {'model': []},
    {'effort': 'invented'}, {'effort': []}, {'harness': 'hermes', 'effort': 'high'},
    {'helper_model': 'another-model'},
    {'allowed_paths': ['result.txt']}, {'tools': {'mcp': ['fixture']}},
    {'claude_chrome': True},
])
def test_invalid_or_unavailable_capabilities_never_register(preview, changes):
    response = server.do_spawn({**preview, 'provider': 'deepseek', 'harness': 'dsh',
                                'model': 'deepseek-fixture', **changes})
    assert response['ok'] is False


def test_availability_is_rechecked_at_post(preview, catalog):
    catalog[0]['models'][0]['harnesses'][0]['available'] = False
    result = server.do_spawn({**preview, 'provider': 'deepseek', 'harness': 'dsh',
                             'model': 'deepseek-fixture'})
    assert result['error_code'] == 'spawn_pair_unavailable'


@pytest.mark.parametrize(('provider', 'aliases'), [
    ('claude', ['claude-code', 'claudecode']), ('codex', ['codex-cli', 'codex']),
])
def test_native_aliases_keep_existing_dispatch(monkeypatch, provider, aliases):
    monkeypatch.setattr(server, '_spawn_request', lambda payload: (None, {'snapshot': payload}))
    payload = {'provider': provider, 'task': 'existing task', 'parent': 'FixtureParent'}
    expected = server.do_spawn(payload)
    for alias in aliases:
        assert server.do_spawn({**payload, 'harness': alias, 'helper_model': 'same'}) == expected


@pytest.mark.parametrize('provider,harness', [('deepseek', 'dsh'), ('strata', 'hermes')])
@pytest.mark.parametrize('asynchronous', [False, True])
def test_registration_binding_and_response_use_standard_name_contract(
        preview, monkeypatch, tmp_path, provider, harness, asynchronous):
    calls, launched = [], []
    monkeypatch.setattr(server, 'RUNTIME_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(server, 'HERE', str(tmp_path))
    monkeypatch.setattr(server, '_spawn_name_status', lambda _: 'available')
    monkeypatch.setattr(server, '_tmux_run', lambda *a, **k: SimpleNamespace(returncode=0))
    def mcp(method, args, **kwargs):
        calls.append((method, args))
        return {'ok': True, 'data': {'name': 'BrightCurie', 'id': 42}}
    monkeypatch.setattr(server, '_mcp_call', mcp)
    monkeypatch.setattr(server.subprocess, 'Popen', lambda args, **kwargs: launched.append((args, kwargs)))
    # No real launcher process: the shared readiness probe is also synthetic.
    result = server.do_spawn({**preview, 'dry_run': False, 'provider': provider, 'harness': harness,
                             'model': provider + '-fixture', 'name': 'Bright-Curie',
                             'async': asynchronous})
    assert result['ok']
    assert result['child_name'] == result['tmux_session'] == 'BrightCurie'
    assert not {'managed', 'attempt_id', 'state'} & result.keys()
    assert calls[0][0] == 'register_agent'
    assert calls[0][1]['program'] == harness
    args, env = launched[0]
    assert args[5:12] == ['--standalone', '--harness', harness, '--backend', provider,
                          '--model', provider + '-fixture']
    assert 'PARENT_AGENT' not in env['env']
    binding = json.loads(Path(args[4] + '.binding.json').read_text())
    assert binding == {'agent_name': 'BrightCurie', 'agent_id': 42,
                       'project_key': '/fixture/project', 'program': harness}
    if asynchronous:
        # Join the existing async launch worker before monkeypatch teardown.
        import threading
        for worker in threading.enumerate():
            if worker.name == 'spawn-BrightCurie':
                worker.join(timeout=2)
        assert server.spawn_launch_status('BrightCurie')['state'] == 'ready'


def test_standard_catalog_shares_i5_without_managed_ui_metadata(monkeypatch, tmp_path):
    capability = {'available': True, 'efforts': ['low', 'high'],
                  'default_effort': 'high', 'effort_source': 'harness'}
    monkeypatch.setattr(managed_catalog, '__file__', str(tmp_path / 'managed_catalog.py'))
    monkeypatch.setattr(managed_catalog, 'load_standard_inputs', lambda *a, **k: (
        {'deepseek': {'model': 'deepseek-fixture', 'effort': 'low'}},
        {'deepseek': {'dsh': capability}}, True))
    row = managed_catalog.standard_catalog('fixture-manifest', mode='legacy')[0]
    assert 'managed' not in row and 'helper_models' not in row
    selected = row['models'][0]['harnesses'][0]
    assert selected['efforts'] == ['low', 'high']
    assert selected['default_effort'] == 'high'  # cache, not the trial input
    assert selected['effort_source'] == 'harness'
    assert 'task_modes' not in selected


def test_standard_catalog_is_off_without_config():
    assert managed_catalog.standard_catalog(None, mode='legacy') == []










