"""Synthetic APFS snapshot and rollback; never touches the real installation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / 'scripts/pre-install-snapshot.py'
POST = ROOT / 'scripts/post-install-restore.py'
CANDIDATE = 'a' * 40


@pytest.fixture
def fixture_tree(tmp_path):
    home = tmp_path / 'home'
    stack = home / '.agentstack'
    (stack / 'bin').mkdir(parents=True)
    (stack / 'backups').mkdir()
    project = home / 'project'
    project.mkdir()
    (stack / 'bin/tool').write_bytes(b'old tool fixture')
    (stack / 'env.sh').write_bytes(b"synthetic private fixture\nexport AGENTSTACK_LABEL_PREFIX=fixture\n")
    (project / 'AGENTS.md').write_bytes(b'old instruction fixture')
    release_hooks = stack / 'releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595/hooks'
    release_hooks.mkdir(parents=True)
    (release_hooks / 'link').symlink_to('tool')
    state = {'owned_files': [str(stack / 'bin/tool')], 'services': [],
             'env': {'AGENTSTACK_LABEL_PREFIX': 'fixture'}}
    (stack / 'install-state.json').write_text(json.dumps(state))
    destination = stack / 'backups/orrery-up-6-fixture'
    return home, project, destination


def run_pre(home, project, destination, overrides=None):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('AGENTSTACK_', 'XDG_'))
           and key not in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR')}
    env['HOME'] = str(home)
    env.update(overrides or {})
    return subprocess.run([sys.executable, str(PRE), '--home', str(home), '--project', str(project),
                           '--candidate', CANDIDATE, '--worktree', str(project), '--destination', str(destination)],
                          capture_output=True, text=True, env=env)


def run_post(home, destination, sha):
    return subprocess.run([sys.executable, str(POST), '--home', str(home), '--snapshot', str(destination),
                           '--manifest-sha256', sha], capture_output=True, text=True)


def test_snapshot_restore_and_preserve_post_install_bytes(fixture_tree):
    home, project, destination = fixture_tree
    result = run_pre(home, project, destination)
    assert result.returncode == 0
    stats = json.loads(result.stdout)
    rows = json.loads((destination / 'manifest.json').read_text())
    assert rows and all(set(row) == {'path', 'sha256', 'bytes'} for row in rows)
    assert stats['files'] >= 4
    assert destination.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o700 for p in destination.rglob('*')
               if p.is_dir() and not p.is_symlink())
    (home / '.agentstack/bin/tool').write_bytes(b'new tool fixture')
    (home / '.agentstack/env.sh').write_bytes(b'new synthetic fixture')
    (project / 'AGENTS.md').write_bytes(b'new instruction fixture')
    result = run_post(home, destination, stats['manifest_sha256'])
    assert result.returncode == 0
    assert (home / '.agentstack/bin/tool').read_bytes() == b'old tool fixture'
    assert (home / '.agentstack/env.sh').read_bytes() == b"synthetic private fixture\nexport AGENTSTACK_LABEL_PREFIX=fixture\n"
    assert (project / 'AGENTS.md').read_bytes() == b'old instruction fixture'
    assert (destination / 'post-install-current/.agentstack/bin/tool').read_bytes() == b'new tool fixture'
    link = home / '.agentstack/releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595/hooks/link'
    assert link.is_symlink()
    assert os.readlink(link) == 'tool'


def test_corrupt_snapshot_stops_before_restore(fixture_tree):
    home, project, destination = fixture_tree
    pre = run_pre(home, project, destination)
    assert pre.returncode == 0
    sha = json.loads(pre.stdout)['manifest_sha256']
    (home / '.agentstack/bin/tool').write_bytes(b'new current fixture')
    (destination / 'files/.agentstack/bin/tool').write_bytes(b'corrupt fixture')
    post = run_post(home, destination, sha)
    assert post.returncode != 0
    assert (home / '.agentstack/bin/tool').read_bytes() == b'new current fixture'
    assert not (destination / 'post-install-current').exists()


def test_clone_mismatch_leaves_no_complete_manifest(fixture_tree, monkeypatch):
    home, project, destination = fixture_tree
    spec = importlib.util.spec_from_file_location('snapshot_test_module', PRE)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    def corrupt(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'not a matching copy')
    monkeypatch.setattr(tool, 'clone', corrupt)
    with pytest.raises(ValueError, match='verification'):
        tool.snapshot(home, project, CANDIDATE, project, destination)
    assert not (destination / 'manifest.json').exists()


def test_owned_path_cannot_traverse_symlink(fixture_tree):
    home, project, destination = fixture_tree
    stack = home / '.agentstack'
    (stack / 'bin/escape').symlink_to(project, target_is_directory=True)
    state = json.loads((stack / 'install-state.json').read_text())
    state['owned_files'].append(str(stack / 'bin/escape/AGENTS.md'))
    (stack / 'install-state.json').write_text(json.dumps(state))
    result = run_pre(home, project, destination)
    assert result.returncode != 0
    assert not destination.exists()


def test_private_plan_lists_actual_paths_without_file_contents(fixture_tree):
    home, project, destination = fixture_tree
    plan_file = home / '.agentstack/backups/plan.json'
    result = subprocess.run([sys.executable, str(PRE), '--home', str(home), '--project', str(project),
                             '--candidate', CANDIDATE, '--worktree', str(project), '--plan', '--plan-output', str(plan_file)],
                            capture_output=True, text=True)
    assert result.returncode == 0
    rows = json.loads(plan_file.read_text())
    assert any(row['path'] == '.agentstack/env.sh' for row in rows)
    assert any(row['path'] == '.agentstack/bin/agentstack-doctor' for row in rows)
    assert any(row['path'] == '.agentstack/hooks/spawn_child.upstream.sh' for row in rows)
    assert all(set(row) == {'path', 'sha256', 'bytes'} for row in rows)
    assert 'synthetic private fixture' not in plan_file.read_text()
    assert plan_file.stat().st_mode & 0o777 == 0o600
    assert not destination.exists()


@pytest.mark.parametrize('key', ['AGENTSTACK_DASHBOARD_LOG', 'AGENTSTACK_MANAGED_AGENTS_FILE',
                                 'AGENTSTACK_DASHBOARD_RUN_STATE'])
@pytest.mark.parametrize('source', ['installed', 'ambient'])
def test_nondefault_runtime_destination_fails_closed(fixture_tree, key, source):
    home, project, destination = fixture_tree
    overrides = {}
    if source == 'installed':
        with (home / '.agentstack/env.sh').open('a') as stream:
            stream.write(f'export {key}=/fixture/other-destination\n')
    else:
        overrides[key] = '/fixture/other-destination'
    result = run_pre(home, project, destination, overrides)
    assert result.returncode != 0
    assert not destination.exists()


@pytest.mark.parametrize('key', ['AGENTSTACK_MAIL_SERVICE_ENV', 'AGENTSTACK_MAIL_SERVICE_VENV',
                                 'AGENTSTACK_MAIL_PACKAGE_SOURCE', 'AGENTSTACK_MAIL_CANDIDATE_ID'])
@pytest.mark.parametrize('value', ['', '/fixture/elsewhere'])
def test_explicit_mail_deployment_destination_fails_closed(fixture_tree, key, value):
    home, project, destination = fixture_tree
    result = run_pre(home, project, destination, {key: value})
    assert result.returncode != 0
    assert not destination.exists()


@pytest.mark.parametrize('key', ['AGENTSTACK_MAIL_DB', 'AGENTSTACK_MAIL_STATE_ROOT',
                                 'AGENTSTACK_MCP_URL', 'AGENTSTACK_MAIL_LAUNCHD_LABEL',
                                 'AGENTSTACK_LABEL_PREFIX'])
def test_changed_live_connection_fails_closed(fixture_tree, key):
    home, project, destination = fixture_tree
    result = run_pre(home, project, destination, {key: '/fixture/elsewhere'})
    assert result.returncode != 0
    assert not destination.exists()


@pytest.mark.parametrize('key,name', [('AGENTSTACK_DASHBOARD_LOG', 'dashboard.log'),
                                       ('AGENTSTACK_MANAGED_AGENTS_FILE', 'managed_agents.txt')])
def test_default_runtime_destination_is_accepted(fixture_tree, key, name):
    home, project, destination = fixture_tree
    with (home / '.agentstack/env.sh').open('a') as stream:
        stream.write(f'export {key}={home}/.agentstack/runtime/{name}\n')
    result = run_pre(home, project, destination)
    assert result.returncode == 0, result.stderr


def test_existing_installer_temporary_files_are_snapshotted(fixture_tree):
    home, project, destination = fixture_tree
    paths = [home / 'Library/LaunchAgents/fixture.mail.plist.prev',
             home / 'Library/LaunchAgents/fixture.mail-watcher.plist.tmp',
             home / '.config/systemd/user/fixture.agentdashboard.service.tmp',
             home / '.agentstack/runtime/annotations.json.tmp',
             home / '.agentstack/runtime/settings-merge-result.json.tmp',
             home / '.agentstack/runtime/settings-installed-entries.json.tmp',
             home / '.agentstack/install-state.json.tmp']
    expected = {}
    for index, path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('fixture-' + str(index)).encode())
        expected[path.relative_to(home).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = run_pre(home, project, destination)
    assert result.returncode == 0, result.stderr
    rows = {r['path']: r for r in json.loads((destination / 'manifest.json').read_text())}
    for path, sha in expected.items():
        assert rows[path]['sha256'] == sha
        assert hashlib.sha256((destination / 'files' / path).read_bytes()).hexdigest() == sha


def test_dashboard_rotation_and_next_migration_destination_are_snapshotted(fixture_tree):
    home, project, destination = fixture_tree
    runtime = home / '.agentstack/runtime'; runtime.mkdir()
    old = runtime / 'dashboard.log.4'; old.write_bytes(b'synthetic old rotation')
    (runtime / 'dashboard.legacy.1.log').write_bytes(b'synthetic legacy')
    result = run_pre(home, project, destination, {'AGENTSTACK_DASHBOARD_LOG_BACKUPS': '5'})
    assert result.returncode == 0, result.stderr
    rows = {row['path'] for row in json.loads((destination / 'manifest.json').read_text())}
    assert '.agentstack/runtime/dashboard.log.5' in rows
    assert '.agentstack/runtime/dashboard.legacy.2.log.tmp' in rows
    assert (destination / 'files/.agentstack/runtime/dashboard.log.4').read_bytes() == old.read_bytes()


def test_existing_examples_are_snapshotted(fixture_tree):
    home, project, destination = fixture_tree
    example = home / '.agentstack/examples/native-harnesses/synthetic.txt'
    example.parent.mkdir(parents=True); example.write_bytes(b'example fixture')
    result = run_pre(home, project, destination)
    assert result.returncode == 0, result.stderr
    assert (destination / 'files/.agentstack/examples/native-harnesses/synthetic.txt').read_bytes() == b'example fixture'


def test_managed_harness_configuration_stops_before_snapshot(fixture_tree):
    home, project, destination = fixture_tree
    setting = home / '.agentstack/dashboard/dsh-provider.json'
    setting.parent.mkdir(parents=True); setting.write_text('not-json-and-must-not-be-read')
    result = run_pre(home, project, destination)
    assert result.returncode != 0
    assert not destination.exists()
    assert setting.read_text() == 'not-json-and-must-not-be-read'


def test_installed_location_drift_stops_without_executing_environment(fixture_tree):
    home, project, destination = fixture_tree
    sentinel = home / 'must-not-exist'
    (home / '.agentstack/env.sh').write_text(
        "export AGENTSTACK_LABEL_PREFIX=fixture\n"
        "export AGENTSTACK_MCP_URL='$(touch " + str(sentinel) + ")'\n")
    result = run_pre(home, project, destination)
    assert result.returncode != 0
    assert not sentinel.exists()
    assert not destination.exists()


def test_cleared_installed_label_fails_closed(fixture_tree):
    home, project, destination = fixture_tree
    (home / '.agentstack/env.sh').write_text("export AGENTSTACK_LABEL_PREFIX=''\n")
    result = run_pre(home, project, destination)
    assert result.returncode != 0
    assert not destination.exists()


def test_missing_nondefault_installed_label_fails_closed(fixture_tree):
    home, project, destination = fixture_tree
    (home / '.agentstack/env.sh').write_text('# label absent\n')
    result = run_pre(home, project, destination)
    assert result.returncode != 0
    assert not destination.exists()


def test_symlinked_stack_root_refused_before_environment_read(tmp_path):
    home = tmp_path / 'home'; home.mkdir()
    external = tmp_path / 'external'; external.mkdir()
    (external / 'env.sh').write_text('synthetic')
    (home / '.agentstack').symlink_to(external, target_is_directory=True)
    project = home / 'project'; project.mkdir()
    result = run_pre(home, project, home / '.agentstack/backups/orrery-up-6-fixture')
    assert result.returncode != 0
    assert not (external / 'backups').exists()


def test_wrong_manifest_digest_refuses_before_restore(fixture_tree):
    home, project, destination = fixture_tree
    pre = run_pre(home, project, destination)
    assert pre.returncode == 0
    (home / '.agentstack/bin/tool').write_bytes(b'new current fixture')
    post = run_post(home, destination, '0' * 64)
    assert post.returncode != 0
    assert (home / '.agentstack/bin/tool').read_bytes() == b'new current fixture'
    assert not (destination / 'post-install-current').exists()


def test_existing_instruction_receipt_adds_resolved_targets(fixture_tree):
    home, project, destination = fixture_tree
    stack = home / '.agentstack'
    legacy = home / 'legacy'; legacy.mkdir()
    target = legacy / 'CLAUDE.md';target.write_bytes(b'old legacy fixture')
    receipt = stack / 'backups/instruction-migration/provider/receipt.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({'plan': {'target': {'requested_path': str(target),
                                                        'resolved_path': str(target)}, 'sources': []}}))
    state = json.loads((stack / 'install-state.json').read_text())
    state['instruction_receipts'] = [str(receipt)]
    (stack / 'install-state.json').write_text(json.dumps(state))
    result = run_pre(home, project, destination)
    assert result.returncode == 0
    assert (destination / 'files/legacy/CLAUDE.md').read_bytes() == b'old legacy fixture'
    assert (destination / 'files/.agentstack/backups/instruction-migration/provider/receipt.json').is_file()


def test_reverify_stops_when_live_file_changes_after_snapshot(fixture_tree):
    home, project, destination = fixture_tree
    result = run_pre(home, project, destination)
    assert result.returncode == 0
    sha = json.loads(result.stdout)['manifest_sha256']
    (home / '.agentstack/bin/tool').write_bytes(b'changed after snapshot')
    verify = subprocess.run([sys.executable, str(PRE), '--home', str(home), '--project', str(project),
                             '--candidate', CANDIDATE, '--worktree', str(project), '--destination', str(destination),
                             '--verify-manifest-sha', sha], capture_output=True, text=True)
    assert verify.returncode != 0
    assert (home / '.agentstack/bin/tool').read_bytes() == b'changed after snapshot'


def test_plan_covers_every_fleet_destination_in_owner_preview(fixture_tree):
    home, project, destination = fixture_tree
    shell = (ROOT / 'scripts/run-mail-fetch-upgrade-from-ref.sh').read_text()
    code = shell.split('  python3 - "$script_root" <<\'PY\'\n', 1)[1].split('\nPY\n', 1)[0]
    result = subprocess.run([sys.executable, '-c', code, str(ROOT)], capture_output=True, text=True)
    assert result.returncode == 0
    preview = [line.removeprefix('fleet destination: ') for line in result.stdout.splitlines()
               if line.startswith('fleet destination: ')]
    assert preview
    spec = importlib.util.spec_from_file_location('snapshot_coverage_module', PRE)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    roots = tool.plan(home, project, CANDIDATE, project)
    missing = [rel for rel in preview if not any('.agentstack/' + rel == root or
               ('.agentstack/' + rel).startswith(root + '/') for root in roots)]
    assert missing == []


def test_unexpected_writable_symlink_stops_before_snapshot(fixture_tree):
    home, project, destination = fixture_tree
    link = home / '.agentstack/bin/unsafe-link'
    link.symlink_to(project / 'AGENTS.md')
    result = run_pre(home, project, destination)
    assert result.returncode != 0
    assert not destination.exists()
