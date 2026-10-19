import json
from types import SimpleNamespace

import pytest

from dashboard import harness_runtime as runtime, managed_catalog, server


@pytest.mark.parametrize('program,command,expected', [
    ('dsh', '/fixed/node /fixed/node_modules/@deepseek-ai/dsh/lib/bin.js --profile x', True),
    ('dsh', '/fixed/node /fixed/mcp/server.js', False),
    ('dsh', 'node', False),
    ('hermes', '/fixed/venv/bin/python /fixed/venv/bin/hermes chat', True),
    ('hermes', 'python3 -m hermes_cli.main chat', True),
    ('hermes', 'hermes', True),
    ('hermes', 'python3 /fixed/mcp.py', False),
    ('hermes', 'zsh', False),
])
def test_native_entry_identity(program, command, expected):
    assert runtime.matches_command(program, command) is expected


@pytest.mark.parametrize('command,returncode,expected', [
    ('node /fixed/node_modules/@deepseek-ai/dsh/lib/bin.js', 0, True),
    ('node /fixed/mcp.js', 0, False),
    ('', 1, None),
])
def test_only_pane_descendants_count(monkeypatch, command, returncode, expected):
    server._NATIVE_COMMAND_CACHE.clear()
    tree = ({10: 'zsh', 11: 'node', 50: 'node'}, {10: [11]})
    calls = []

    def ps(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=returncode, stdout=command)

    monkeypatch.setattr(server.subprocess, 'run', ps)
    assert server._agent_process_alive(10, tree, 'dsh') is expected
    assert calls == [['ps', '-p', '11', '-o', 'args=']]
    assert server.classify('FixtureAgent', 'node', '', True, 'dsh', expected) == (
        'finished' if expected is False else 'agent')


def test_backend_metadata_never_uses_model_vendor(tmp_path):
    directory = tmp_path / 'child-agents'
    directory.mkdir()
    file = directory / 'FixtureAgent.json'
    record = dict(agent_name='FixtureAgent', program='hermes', harness='hermes',
                  harness_backend='strata', model='claude-looking-model')
    file.write_text(json.dumps(record))
    assert runtime.metadata(tmp_path, 'FixtureAgent', 'hermes') == {
        'harness': 'hermes', 'provider': 'strata', 'locality': 'local'}
    record['agent_name'] = 'OtherAgent'
    file.write_text(json.dumps(record))
    assert runtime.metadata(tmp_path, 'FixtureAgent', 'hermes')['provider'] == ''
    file.unlink()
    file.symlink_to('/missing-fixture')
    assert runtime.metadata(tmp_path, 'FixtureAgent', 'hermes')['provider'] == ''


@pytest.mark.parametrize('alive', [True, False, None])
def test_views_and_controls_agree_on_native_liveness(monkeypatch, tmp_path, alive):
    name = 'FixtureAgent'
    session = dict(name=name, created=100, session_id='$1', activity=200,
                   attached=False, client_tty=None, cmd='node', pane_pid=10,
                   title='unparsed native TUI')
    registration = dict(model='gpt-fixture', model_raw='gpt-fixture', program='dsh',
                        task='fixture', last_active=150)
    directory = tmp_path / 'child-agents'
    directory.mkdir()
    (directory / (name + '.json')).write_text(json.dumps(dict(
        agent_name=name, program='dsh', harness='dsh', harness_backend='strata')))
    monkeypatch.setattr(server, 'RUNTIME_DIR', str(tmp_path))
    monkeypatch.setattr(server, 'tmux_state', lambda: {name: session})
    monkeypatch.setattr(server, 'agentmail_state', lambda: ({name: registration}, {}))
    monkeypatch.setattr(server, '_mail_agent_for', lambda _: registration)
    monkeypatch.setattr(server, '_process_tree_snapshot', lambda: ({10: 'node'}, {}))
    monkeypatch.setattr(server, '_agent_process_alive', lambda *a: alive)
    for function in ('_codex_app_runtimes', '_deliverables_index', '_name_substitutions',
                     '_annotations', '_persistent_profiles'):
        monkeypatch.setattr(server, function, lambda: {})
    monkeypatch.setattr(server, '_retired_names', lambda *a: set())
    monkeypatch.setattr(server, '_project_key', lambda: '')
    monkeypatch.setattr(server, '_resume_capability_for_row', lambda *a, **k: 'not_required')
    monkeypatch.setattr(server, '_provider_stall_view', lambda *a: None)
    monkeypatch.setattr(server, '_agent_runtime', lambda *a: pytest.fail('foreign TUI parser'))
    monkeypatch.setattr(server, '_raw_graph', lambda: dict(nodes=[dict(
        name=name, program='dsh', model='gpt-fixture', last_active=200, retired=False)],
        edges=[], spawn=[]))
    roster = server.build_agents()[0]
    lookup = server.lookup_agent(name)
    node = server.graph_payload(4, True)['nodes'][0]
    for row in (roster, lookup, node):
        assert row['running'] is (alive is True)
        assert row['provider'] == 'strata' and row['harness'] == 'dsh'
    assert roster['category'] == lookup['category'] == ('finished' if alive is False else 'agent')
    assert node['state'] == ('unknown' if alive is None else 'run' if alive else 'finished')
    monkeypatch.setattr(server, '_managed_spawn_manager', lambda: SimpleNamespace(stop=lambda _: None))
    if alive is not False:
        assert server.do_kill(name)['ok'] is False


def test_catalog_uses_shared_selection_and_capability_cache(monkeypatch, tmp_path):
    manifest = tmp_path / 'manifest.json'
    config = tmp_path / 'config.json'
    config.write_text('{}')
    manifest.write_text(json.dumps({'enabled': True, 'backends': {
        'deepseek': {'model': 'fixture-model'}}}))
    monkeypatch.setattr(managed_catalog, '__file__', str(tmp_path / 'managed_catalog.py'))
    monkeypatch.setattr(managed_catalog.sys, 'platform', 'darwin')
    calls = []

    def select(file, harness, backend, model):
        calls.append((file, harness, backend, model))
        if harness == 'hermes':
            raise ValueError('plain_generation_required')
        return {'config_file': str(config)}

    monkeypatch.setattr(managed_catalog, '_thin_selection', select)
    monkeypatch.setattr(managed_catalog, 'load_effort_capability', lambda *a, **k: {
        'efforts': ['low', 'high'], 'default_effort': 'high', 'effort_source': 'harness'})
    row = managed_catalog.standard_catalog(str(manifest), mode='legacy')[0]
    choices = row['models'][0]['harnesses']
    assert choices[0]['available'] is True and choices[0]['efforts'] == ['low', 'high']
    assert choices[1]['available'] is False
    assert choices[1]['reason'] == 'plain_generation_required'
    assert len(calls) == 2
    (tmp_path / 'dsh-provider.json').write_text('{"enabled":false}')
    assert not managed_catalog.standard_catalog(str(manifest), mode='legacy')[0]['models'][0]['harnesses'][0]['available']


def test_shared_helper_import_is_independent_of_cwd(monkeypatch, tmp_path):
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    dashboard = tmp_path / 'dashboard'
    dashboard.mkdir()
    (hooks / 'child_resume.py').write_text('FIXTURE = 17\n')
    (hooks / 'harness_child.py').write_text(
        'from . import child_resume\n'
        'def selection(*args): return child_resume.FIXTURE, args\n')
    monkeypatch.setattr(managed_catalog, '__file__', str(dashboard / 'managed_catalog.py'))
    monkeypatch.chdir('/')
    assert managed_catalog._thin_selection('manifest', 'dsh', 'strata', 'model') == (
        17, ('manifest', 'dsh', 'strata', 'model'))
