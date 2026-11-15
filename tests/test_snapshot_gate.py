"""The owner entry must never run the installer after snapshot failure."""
import os
from pathlib import Path
import pty
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'scripts/run-mail-fetch-upgrade-from-ref.sh'


@pytest.mark.parametrize('failure_stage', ['plan', 'plan-mismatch', 'snapshot', 'verify', 'dirty', 'none'])
def test_snapshot_gate_controls_installer(tmp_path, failure_stage):
    repo = tmp_path / 'repo'
    scripts = repo / 'scripts'
    scripts.mkdir(parents=True)
    (scripts / 'run-mail-fetch-upgrade-from-ref.sh').write_bytes(ENTRY.read_bytes())
    (scripts / 'pre-install-snapshot.py').write_text('''import hashlib,json,os,pathlib,sys
if '--plan' in sys.argv:
    if os.environ.get('TEST_FAILURE_STAGE') == 'plan': raise SystemExit(1)
    pathlib.Path(sys.argv[-1]).write_text('[{\"path\":\"fixture\"}]' if os.environ.get('TEST_FAILURE_STAGE') == 'plan-mismatch' else '[]');raise SystemExit(0)
if '--verify-manifest-sha' in sys.argv:
    if os.environ.get('TEST_FAILURE_STAGE') == 'dirty':
        (pathlib.Path(os.environ['TEST_REPO'])/'scripts/install.sh').write_text('dirty fixture')
    raise SystemExit(1 if os.environ.get('TEST_FAILURE_STAGE') == 'verify' else 0)
if os.environ.get('TEST_FAILURE_STAGE') == 'snapshot': raise SystemExit(1)
p=pathlib.Path(sys.argv[-1]);p.mkdir();m=p/'manifest.json';m.write_text('[]')
print(json.dumps({'manifest_sha256':hashlib.sha256(m.read_bytes()).hexdigest()}))
''')
    (scripts / 'install.sh').write_text('#!/bin/bash\nprintf installed > "$TEST_MARKER"\n')
    home = tmp_path / 'home'
    (home / '.agentstack/backups').mkdir(parents=True)
    project = home / 'project'; project.mkdir()
    fake = tmp_path / 'fake'; fake.mkdir()
    governor = fake / 'dev-storage-governor'
    governor.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_ALLOC"\n');governor.chmod(0o755)
    station = fake / 'agentstack-station-materials'
    station.write_text('#!/bin/sh\nexit 1\n');station.chmod(0o755)
    allocation = tmp_path / 'allocation';allocation.mkdir()
    (allocation / 'source').symlink_to(repo, target_is_directory=True)
    env = {'HOME': str(home), 'PATH': str(fake) + ':/opt/homebrew/bin:/usr/bin:/bin',
           'USER': 'fixture', 'GIT_CONFIG_NOSYSTEM': '1', 'TEST_ALLOC': str(allocation),
           'TEST_MARKER': str(tmp_path / 'installer-ran'), 'TEST_FAILURE_STAGE': failure_stage, 'TEST_REPO': str(repo),
           'AGENTSTACK_UPGRADE_REPO': str(repo), 'AGENTSTACK_PROJECT_KEY': str(project)}
    subprocess.run(['git', 'init', '-q', str(repo)], env=env, check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'add', 'scripts'], env=env, check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=fixture', '-c', 'user.email=fixture@local',
                    'commit', '-qm', 'fixture'], env=env, check=True, capture_output=True)
    sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], env=env, text=True).strip()
    env['AGENTSTACK_UPGRADE_REF'] = sha
    master, slave = pty.openpty()
    try:
        result = subprocess.run(['/bin/bash', str(scripts / 'run-mail-fetch-upgrade-from-ref.sh')],
                                env=env, stdin=slave, capture_output=True, text=True, timeout=30)
    finally:
        os.close(master);os.close(slave)
    if failure_stage != 'none':
        assert result.returncode != 0
        assert not (tmp_path / 'installer-ran').exists()
    else:
        assert result.returncode == 0
        assert (tmp_path / 'installer-ran').read_text() == 'installed'
