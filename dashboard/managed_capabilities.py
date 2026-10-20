"""Local, keyless effort metadata. Unknown is never a copied trial default."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone

UNKNOWN = {'efforts': None, 'default_effort': None, 'effort_source': 'unknown'}


def read(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def model_input(backend_id, backend):
    model = backend['model']
    if not isinstance(model, str) or not model.strip():
        raise ValueError('Configured model required')
    result = {'model': model, 'model_definition': backend.get('model_definition')}
    if backend.get('thinking') is not None:
        result['thinking'] = backend['thinking']
    # Explicit effort/output overrides do not describe the model's capabilities.
    return {'backend_id': backend_id, **result, 'model_fingerprint': digest(result)}


def runtime_facts(template):
    modules = Path(template['runtime']) / 'node_modules'
    versions, hashes = {}, {}
    for name, label in [('@deepseek-ai/dsh', 'dsh'), ('@deepseek-harness-tui/dsh-tui', 'tui')]:
        versions[label] = read(modules / name / 'package.json')['version']
    for name in ('@deepseek-ai/dsh-llm', '@deepseek-ai/dsh-llm-deepseek'):
        hashes[name] = hashlib.sha256((modules / name / 'lib/index.js').read_bytes()).hexdigest()
    return {'runtime_versions': versions, 'runtime_fingerprint': digest({'versions': versions, 'hashes': hashes})}


def cache_file(template):
    return Path(template['runtime']).parent / 'evidence/effort-capabilities.json'


def _literal_assignment(tree, name):
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return ast.literal_eval(node.value)
    raise ValueError('Missing native reasoning declaration')


def hermes_effort_capability(template):
    """Read the native custom-route vocabulary and default as data, never import it.

    Named key_cmd providers use CustomProfile. Intersect its actual wire levels
    with the CLI parser's levels: disabled is not a graded level, and an internal
    level clamped to another wire value is not a separate slider step.
    """
    source = Path(template['hermes_source'])
    cli = ast.parse((source / 'hermes_constants.py').read_text())
    wire = ast.parse((source / 'agent/reasoning_effort.py').read_text())
    custom = ast.parse((source / 'plugins/model-providers/custom/__init__.py').read_text())
    levels = _literal_assignment(cli, 'VALID_REASONING_EFFORTS')
    profile = next(node for node in custom.body if isinstance(node, ast.ClassDef) and node.name == 'CustomProfile')
    methods = {node.name: node for node in profile.body if isinstance(node, ast.FunctionDef)}
    def returned(name):
        body = [node for node in methods[name].body if not (isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))]
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            raise ValueError('Native reasoning policy changed')
        return body[0].value
    vocabulary = returned('supported_reasoning_efforts')
    if not isinstance(vocabulary, ast.Name):
        raise ValueError('Native wire vocabulary changed')
    supported = _literal_assignment(wire, vocabulary.id)
    default_config = ast.literal_eval(returned('default_reasoning_config'))
    if (not isinstance(levels, (tuple, list)) or not isinstance(supported, (tuple, list))
            or not all(isinstance(value, str) and value for value in (*levels, *supported))
            or not isinstance(default_config, dict) or default_config.get('enabled') is not True):
        raise ValueError('Invalid native reasoning metadata')
    efforts = list(dict.fromkeys(value for value in levels if value in supported))
    default = default_config.get('effort')
    if not efforts or default not in efforts:
        raise ValueError('Unknown native reasoning default')
    return {'efforts': efforts, 'default_effort': default, 'effort_source': 'harness'}


def load_effort_capability(template, *, harness, backend_id, model):
    """Read checked metadata only. No process, provider or credential calls."""
    if harness == 'hermes':
        try:
            if backend_id not in template.get('profiles', {}) or not isinstance(model, str) or not model:
                return dict(UNKNOWN)
            return hermes_effort_capability(template)
        except (OSError, ValueError, KeyError, TypeError, SyntaxError, StopIteration, UnicodeError):
            return dict(UNKNOWN)
    if harness != 'dsh':
        return dict(UNKNOWN)
    try:
        backend = read(template['backend_file'])['backends'][backend_id]
        row_input = model_input(backend_id, backend)
        facts, cached = runtime_facts(template), read(cache_file(template))
        if (model != row_input['model'] or cached['schema_version'] != 1 or cached['harness'] != harness
                or cached['runtime_fingerprint'] != facts['runtime_fingerprint']):
            return dict(UNKNOWN)
        rows = [r for r in cached['entries'] if r['backend_id'] == backend_id and r['model'] == model
                and r['model_fingerprint'] == row_input['model_fingerprint']]
        if len(rows) != 1 or rows[0]['source'] != 'harness':
            return dict(UNKNOWN)
        efforts, default = rows[0]['efforts'], rows[0]['default_effort']
        if (not isinstance(efforts, list) or not all(isinstance(v, str) and v.strip() for v in efforts)
                or len(set(efforts)) != len(efforts) or default is not None and default not in efforts):
            return dict(UNKNOWN)
        return {'efforts': list(efforts), 'default_effort': default, 'effort_source': 'harness'}
    except (OSError, ValueError, KeyError, TypeError):
        return dict(UNKNOWN)


def refresh_dsh_capabilities(repo, current, config_file=None):
    """Installer-owned runtime evidence. Read only selected non-secret model facts."""
    target = cache_file(current)
    cached = {'schema_version': 1, 'harness': 'dsh', 'entries': [],
              'runtime_fingerprint': None, 'runtime_versions': {},
              'generated_at': datetime.now(timezone.utc).isoformat(), 'extraction_status': 'unknown'}
    try:
        cached.update(runtime_facts(current))
        entries = []
        if config_file:
            manifest = read(config_file)
            if manifest.get('enabled') is True and 'dsh' in manifest.get('harnesses', {}):
                template = read(manifest['harnesses']['dsh']['config_file'])
                configured = read(template['backend_file'])['backends']
                for backend_id, public in manifest.get('backends', {}).items():
                    if backend_id not in ('deepseek', 'strata') or backend_id not in configured:
                        continue
                    row = model_input(backend_id, configured[backend_id])
                    if row['model'] == public.get('model'):
                        entries.append(row)
        if entries:
            with tempfile.TemporaryDirectory(prefix='effort-capabilities-') as home:
                # Never inherit Keychain hooks, provider keys, NODE_OPTIONS or Mail binding.
                env = {'HOME': home, 'PATH': os.defpath}
                completed = subprocess.run([current['node'], str(Path(repo) / 'integrations/dsh/capabilities.mjs')],
                    input=json.dumps({'runtime': current['runtime'], 'entries': entries}),
                    text=True, capture_output=True, check=True, timeout=30, env=env, cwd=home)
            result = json.loads(completed.stdout)
            if result.get('forwarded') != 0 or result.get('network_attempts') != 0:
                raise ValueError('Capability extraction attempted network')
            cached['entries'] = result['entries']
        cached['extraction_status'] = 'known'
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # A normal update/import failure must not keep old known metadata alive.
        cached['entries'] = []
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cached, indent=2) + '\n')
    target.chmod(0o600)
    return cached
