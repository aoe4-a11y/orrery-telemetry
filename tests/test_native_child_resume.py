"""Native resume reads only the exact child's callback and retained identity."""
import json

import pytest

from hooks import child_resume as resume
from dashboard import server


def child(tmp_path, name, harness='dsh', native_id='session-one'):
    runtime = tmp_path / 'runtime'
    directory = runtime / 'child-agents' / (name + '.harness') / ('a' * 32)
    state = dict(schema_version=1, launch_origin='child', provider=harness,
                 agent_name=name, agent_id=73 if name == 'FirstAgent' else 74,
                 project_key='/fixture/project', program=harness,
                 registration_token='fixture-token-' + name,
                 harness=harness, harness_backend='strata', harness_state_dir=str(directory),
                 retired_at='2026-10-19T00:00:00Z', resume_expires_at='2099-01-01T00:00:00Z')
    document = dict(agent_name=name, program=harness, backend_id='strata',
                    model='fixture-model', project_key=state['project_key'],
                    cwd=str(tmp_path), state_dir=str(directory), runtime_dir=str(runtime))
    event = dict(harness=harness, native_session_id=native_id,
                 created_at='2026-10-19T00:00:00Z', agent_name=name)
    for path, value in [(directory / 'native-session.json', event),
                        (directory / 'input.json', document),
                        (runtime / 'child-agents' / (name + '.json'), state)]:
        resume._atomic_json(path, value)
    resume._atomic_bytes(runtime / ('agent_token_' + name), state['registration_token'].encode())
    return runtime, state, document, event


@pytest.mark.parametrize('harness', ['dsh', 'hermes'])
def test_two_children_resume_only_their_own_id(tmp_path, harness):
    runtime, first, _, _ = child(tmp_path, 'FirstAgent', harness, 'first-native-id')
    _, second, _, _ = child(tmp_path, 'SecondAgent', harness, 'second-native-id')
    for state, expected in [(first, 'first-native-id'), (second, 'second-native-id')]:
        retained = resume.inspect_retained(runtime, state['agent_name'],
            agent_id=state['agent_id'], project_key=state['project_key'], program=harness)
        assert resume.native_resume_input(runtime, retained)['resume_session_id'] == expected


@pytest.mark.parametrize('mismatch', ['directory', 'event_name', 'event_harness',
                                      'input_backend', 'input_name', 'unsafe_id'])
def test_foreign_or_invalid_native_binding_is_rejected(tmp_path, mismatch):
    runtime, state, document, event = child(tmp_path, 'FirstAgent')
    _, other, _, _ = child(tmp_path, 'SecondAgent')
    directory = resume.Path(state['harness_state_dir'])
    if mismatch == 'directory':
        state['harness_state_dir'] = other['harness_state_dir']
    elif mismatch == 'event_name':
        event['agent_name'] = 'SecondAgent'
    elif mismatch == 'event_harness':
        event['harness'] = 'hermes'
    elif mismatch == 'input_backend':
        document['backend_id'] = 'deepseek'
    elif mismatch == 'input_name':
        document['agent_name'] = 'SecondAgent'
    else:
        event['native_session_id'] = '../latest'
    resume._atomic_json(directory / 'native-session.json', event)
    resume._atomic_json(directory / 'input.json', document)
    with pytest.raises(resume.ResumeStateError) as caught:
        resume.native_resume_input(runtime, state)
    assert caught.value.code == 'identity_mismatch'


def test_missing_callback_does_not_fall_back_to_latest(tmp_path):
    runtime, state, _, _ = child(tmp_path, 'FirstAgent')
    directory = resume.Path(state['harness_state_dir'])
    (directory / 'native-session.json').unlink()
    (directory / 'last-used.json').write_text(json.dumps({'session_id': 'foreign-latest'}))
    with pytest.raises(resume.ResumeStateError) as caught:
        resume.native_resume_input(runtime, state)
    assert caught.value.code == 'no_history'


def test_expired_native_identity_cannot_be_reactivated(tmp_path):
    runtime, state, _, _ = child(tmp_path, 'FirstAgent', 'hermes')
    state['resume_expires_at'] = '2026-01-01T00:00:00Z'
    resume._atomic_json(runtime / 'child-agents/FirstAgent.json', state)
    with pytest.raises(resume.ResumeStateError) as caught:
        resume.inspect_retained(runtime, 'FirstAgent', agent_id=73,
                                project_key=state['project_key'], program='hermes')
    assert caught.value.code == 'retention_expired'


@pytest.mark.parametrize('harness', ['dsh', 'hermes'])
@pytest.mark.parametrize('launch_ok', [True, False])
def test_native_dashboard_dispatch_and_failed_startup_rollback(tmp_path, monkeypatch, harness, launch_ok):
    runtime, state, _, _ = child(tmp_path, 'FirstAgent', harness, 'owned-session')
    registration = {key: state[key] for key in ('agent_name', 'agent_id', 'project_key', 'program')}
    monkeypatch.setattr(server, 'RUNTIME_DIR', str(runtime))
    monkeypatch.setattr(server, '_child_resume_module', lambda: resume)
    monkeypatch.setattr(server, '_agent_program', lambda _: harness)
    monkeypatch.setattr(server, '_resume_registration', lambda *a: registration)
    monkeypatch.setattr(server, '_native_resume_launcher_ready', lambda: True)
    monkeypatch.setattr(server, '_register_claude_resume', lambda *a, **k: True)
    mail, launches = [], []
    monkeypatch.setattr(server, '_set_claude_mail_retired', lambda *a, **k: mail.append(k['retired']))
    def launch(argv, **kwargs):
        launches.append((argv, kwargs))
        return {'ok': launch_ok, 'adapter': 'detached'}
    monkeypatch.setattr(server, '_launch_claude_resume_tmux', launch)
    assert server._resume_capability('FirstAgent', harness, category='retired', open_terminal=False) == 'ready'
    answer = server.do_resume('FirstAgent', open_terminal=False, replace_husk=True)
    assert answer['ok'] is launch_ok
    argv, options = launches[0]
    assert argv[-1].endswith('--resume-native FirstAgent')
    assert options['replace_husk'] is True and options['open_terminal'] is False
    assert mail == ([False] if launch_ok else [False, True])
    current = resume._load_state(runtime / 'child-agents/FirstAgent.json')
    assert ('resume_in_progress_at' in current) is launch_ok


def test_native_missing_id_is_unavailable_before_mail_or_tmux(tmp_path, monkeypatch):
    runtime, state, _, _ = child(tmp_path, 'FirstAgent')
    (resume.Path(state['harness_state_dir']) / 'native-session.json').unlink()
    monkeypatch.setattr(server, 'RUNTIME_DIR', str(runtime))
    monkeypatch.setattr(server, '_child_resume_module', lambda: resume)
    monkeypatch.setattr(server, '_resume_registration', lambda *a: state)
    monkeypatch.setattr(server, '_register_claude_resume', lambda *a: pytest.fail('Mail called'))
    monkeypatch.setattr(server, '_launch_claude_resume_tmux', lambda *a, **k: pytest.fail('tmux called'))
    assert server._resume_capability('FirstAgent', 'dsh', category='retired', open_terminal=False) == 'no_history'
    assert server._do_resume_native('FirstAgent', 'dsh')['resume_capability'] == 'no_history'
