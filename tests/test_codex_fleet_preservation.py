"""Protect unique existing Codex integration files during fleet upgrades."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'integrations/codex_app'


def run_copy(destination):
    shell = (ROOT / 'scripts/install.sh').read_text()
    marker = 'source, dest = (pathlib.Path(p) for p in sys.argv[1:3])'
    position = shell.index(marker)
    start = shell.rfind('import os\n', 0, position)
    end = shell.index('\nPY\n', position)
    code = shell[start:end]
    env = dict(os.environ, AGENTSTACK_FLEET_COMPAT='1')
    return subprocess.run([sys.executable, '-c', code, str(SOURCE), str(destination)],
                          env=env, capture_output=True, text=True)


def test_existing_equivalent_schema_and_readme_survive(tmp_path):
    dest = tmp_path / '.agentstack/integrations/codex_app'
    schemas = dest / 'schemas'
    schemas.mkdir(parents=True)
    schema = json.loads((SOURCE / 'schemas/binding-record-v1.json').read_text())
    schema['title'] = 'fixture title retained'
    old_schema = json.dumps(schema).encode()
    (schemas / 'binding-record-v1.json').write_bytes(old_schema)
    (schemas / 'README.md').write_text('existing fixture documentation')
    result = run_copy(dest)
    assert result.returncode == 0
    assert (schemas / 'binding-record-v1.json').read_bytes() == old_schema
    assert (schemas / 'README.md').read_text() == 'existing fixture documentation'
    for candidate in (SOURCE / 'schemas').iterdir():
        if candidate.is_file():
            assert (schemas / candidate.name).is_file()
    assert (dest / 'plugin/scripts/run-mcp.sh').is_file()


def test_incompatible_schema_stops_before_any_payload_write(tmp_path):
    dest = tmp_path / '.agentstack/integrations/codex_app'
    schemas = dest / 'schemas'
    schemas.mkdir(parents=True)
    schema = json.loads((SOURCE / 'schemas/binding-record-v1.json').read_text())
    schema['type'] = 'fixture incompatible type'
    saved = json.dumps(schema).encode()
    (schemas / 'binding-record-v1.json').write_bytes(saved)
    result = run_copy(dest)
    assert result.returncode != 0
    assert (schemas / 'binding-record-v1.json').read_bytes() == saved
    assert not (dest / 'plugin').exists()


def test_unknown_existing_code_stops_before_any_payload_write(tmp_path):
    dest = tmp_path / '.agentstack/integrations/codex_app'
    target = dest / 'plugin/unknown-fixture.py'
    target.parent.mkdir(parents=True)
    target.write_text('unique fixture data')
    result = run_copy(dest)
    assert result.returncode != 0
    assert target.read_text() == 'unique fixture data'
    assert not (dest / 'src').exists()
