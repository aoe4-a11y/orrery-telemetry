"""Bounded, synthetic memory regressions; never operate on live manifests."""
import importlib.util
import faulthandler
import json
import os
from pathlib import Path
import signal
import sys
import tracemalloc
from unittest.mock import patch

import pytest

faulthandler.register(signal.SIGUSR1, all_threads=True)

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path.home() / '.agentstack/bin'))
spec = importlib.util.spec_from_file_location('memory_test_subject', os.environ.get(
    'RETAINPRUNE_SUBJECT', str(Path.home() / '.agentstack/bin/agentstack_retainprune.py')))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
sys.path.insert(0, str(p.RELEASE))
from dev_storage_governor import storage_v6 as v6


def inputs(root):
    manifest = root / 'current.json'
    manifest.write_text(json.dumps(dict(version=1, complete=True,
        protected_paths=[], current_builds=[], current_inputs=[], distributed_archives=[])))
    policy = dict(retention_policy_version='6.0', retention_current_manifest=str(manifest))
    return manifest, policy


def test_prefix_scan_never_stats_impossible_long_paths(tmp_path):
    """Focused regression: impossible long prefixes never need a stat."""
    manifest, policy = inputs(tmp_path)
    files = [tmp_path / ('f%03d.json' % i) for i in range(64)]
    for file in files:
        file.write_text('{}')
    argv = 'copy-files ' + ' '.join(map(str, files))
    longest = 0
    original_file, original_dir = Path.is_file, Path.is_dir
    def measured(method):
        def wrapped(path, *args, **kwargs):
            nonlocal longest
            longest = max(longest, len(os.fsencode(path)))
            return method(path, *args, **kwargs)
        return wrapped
    with patch.object(v6, 'process_paths', lambda: v6.ProcessPaths([argv])), \
         patch.object(Path, 'is_file', measured(original_file)), \
         patch.object(Path, 'is_dir', measured(original_dir)):
        protection = p.validator(policy)
    assert set(files).issubset(protection.targets)
    assert longest < os.pathconf('/', 'PC_PATH_MAX')


def test_wide_fake_tree_does_not_retain_failed_prefixes(tmp_path):
    """Counterexample: a wide fake tree and long copy argv stay below 8 MiB."""
    manifest, policy = inputs(tmp_path)
    tree = tmp_path / 'fake-tree'
    tree.mkdir()
    files = [tree / ('f%04d.json' % i) for i in range(256)]
    for file in files:
        file.write_text('{}')
    argv = 'copy-files ' + ' '.join(map(str, files))
    # Directory targets protect the tree, but must not enter its children.
    policy['retention_current_manifest'] = str(manifest)
    value = json.loads(manifest.read_text())
    value['protected_paths'] = [str(tree)]
    manifest.write_text(json.dumps(value))
    before = manifest.read_bytes()
    with patch.object(v6, 'process_paths', lambda: v6.ProcessPaths([argv])), \
         patch.object(Path, 'rglob', side_effect=AssertionError('no recursive sweep')):
        tracemalloc.start()
        try:
            protection = p.validator(policy)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert set(files).issubset(protection.targets)
    assert tree in protection.targets
    assert manifest.read_bytes() == before
    assert peak < 8 * 1024**2, peak


def test_existing_space_path_protection_and_release_restored(tmp_path):
    manifest, policy = inputs(tmp_path)
    config = tmp_path / 'existing directory with spaces' / 'settings.json'
    config.parent.mkdir()
    config.write_text('{}')
    argv = 'copy-files --config ' + str(config)
    original_paths, original_read = v6.ProcessPaths, v6.r.record_bytes
    with patch.object(v6, 'process_paths', lambda: v6.ProcessPaths([argv])):
        protection = p.validator(policy)
    assert config in protection.targets
    assert v6.ProcessPaths is original_paths
    assert v6.r.record_bytes is original_read


def test_guard_stops_only_own_over_budget_child(monkeypatch):
    monkeypatch.setattr(p, 'MEMORY_LIMIT', 16 * 1024**2)
    script = ('import faulthandler,signal,time; faulthandler.register(signal.SIGUSR1); '
              'x=bytearray(32*1024**2); time.sleep(10)')
    with pytest.raises(p.SweepBudgetExceeded) as exc:
        p.guarded_run(['/opt/homebrew/bin/python3', '-c', script], timeout=5)
    assert exc.value.resource == 'physical_footprint_bytes'
    assert exc.value.observed > exc.value.limit


def test_budget_dry_run_no_mutation_or_transport(tmp_path, monkeypatch):
    manifest, policy = inputs(tmp_path)
    policy_file = tmp_path / 'policy.json'
    policy_file.write_text(json.dumps(policy))
    state = tmp_path / 'state.json'
    before = {f.name: f.read_bytes() for f in tmp_path.iterdir()}
    def exceeded(*args, **kwargs):
        raise p.SweepBudgetExceeded('physical_footprint_bytes', 900, 800)
    monkeypatch.setattr(p, 'guarded_run', exceeded)
    monkeypatch.setattr(p, 'send_server', lambda *_: pytest.fail('dry-run must not send'))
    result = p.sweep(policy_file, manifest, state, dry_run=True)
    assert result['kind'] == 'unknown'
    assert result['scope'] == 'sweep_budget'
    assert {f.name: f.read_bytes() for f in tmp_path.iterdir()} == before


def test_budget_notice_persisted_once_on_non_dry_synthetic_inputs(tmp_path, monkeypatch):
    manifest, policy = inputs(tmp_path)
    policy_file = tmp_path / 'policy.json'
    policy_file.write_text(json.dumps(policy))
    state = tmp_path / 'state.json'
    def exceeded(*args, **kwargs):
        raise p.SweepBudgetExceeded('physical_footprint_bytes', 900, 800)
    notices = []
    monkeypatch.setattr(p, 'guarded_run', exceeded)
    monkeypatch.setattr(p, 'send_server', lambda event: notices.append(event) or {'id': 1})
    for _ in range(2):
        result = p.sweep(policy_file, manifest, state)
        assert result['kind'] == 'unknown'
    assert len(notices) == 1
    saved = json.loads(state.read_text())
    assert next(iter(saved['events'].values()))['status'] == 'sent'


def test_prefix_budget_fails_closed_and_restores_release(tmp_path, monkeypatch):
    manifest, policy = inputs(tmp_path)
    original_paths, original_read = v6.ProcessPaths, v6.r.record_bytes
    monkeypatch.setattr(p, 'PREFIX_LIMIT', 1)
    with patch.object(v6, 'process_paths', lambda: v6.ProcessPaths(['tool /a /b'])):
        with pytest.raises(p.SweepBudgetExceeded):
            p.validator(policy)
    assert v6.ProcessPaths is original_paths
    assert v6.r.record_bytes is original_read


def test_oversized_reference_unknown_no_read_or_mutation(tmp_path):
    manifest, policy = inputs(tmp_path)
    huge = tmp_path / 'huge.json'
    with huge.open('wb') as stream:
        stream.truncate(p.REFERENCE_LIMIT + 1)
    value = json.loads(manifest.read_text())
    value['current_inputs'] = [str(huge)]
    manifest.write_text(json.dumps(value))
    policy_file = tmp_path / 'policy.json'
    policy_file.write_text(json.dumps(policy))
    before = manifest.read_bytes()
    with patch.object(v6, 'process_paths', return_value=set()):
        result = p.check_once(policy_file, manifest, tmp_path / 'state.json', dry_run=True)
    assert result['kind'] == 'unknown'
    assert result['resource'] == 'reference_bytes'
    assert manifest.read_bytes() == before
    assert not (tmp_path / 'state.json').exists()


def test_footprint_positive_control():
    assert 0 < p.physical_footprint(os.getpid()) < 2 * 1024**3
