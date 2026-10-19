"""Generate native Hermes configuration without acquiring credentials.

Read-only admission is shared by the launcher and catalog. The CLI emits a
native argv/env plan; Hermes owns its session, tools, provider and lifetime.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
from urllib.parse import urlsplit

THIN_CONFIG_CONTRACT = 1
HELPER_MODEL_CONTRACT = 1
PLUGIN = 'orrery-thin-guard'
EFFORTS = {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}


def read(path):
    text = Path(path).read_text(encoding='utf-8')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Data parser only: never import Hermes (which can bootstrap at import).
        from ruamel.yaml import YAML
        parser = YAML(typ='safe')
        parser.version = (1, 1)
        return parser.load(text) or {}


def _provider_ids(source):
    tree = ast.parse((source / 'hermes_cli/auth.py').read_text())
    rows = next(node.value for node in tree.body if isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name) and node.target.id == '_REGISTRY_ROWS')
    names = {'openrouter'}
    for row in rows.elts:
        first = row.elts[0] if isinstance(row, ast.Tuple) else row.args[0]
        names.add(ast.literal_eval(first))
    return names


def validate_input(document):
    """Read-only static selection. Raises fixed reasons, never helper output."""
    try:
        return _validate(document)
    except ValueError as error:
        if str(error) in {'unknown_backend', 'model_mismatch', 'invalid_effort',
                          'builtin_provider_collision', 'invalid_runtime', 'invalid_route',
                          'invalid_helper_model', 'invalid_resume_session_id'}:
            raise
        raise ValueError('invalid_runtime') from None
    except (OSError, KeyError, TypeError, StopIteration, SyntaxError, AttributeError):
        raise ValueError('invalid_runtime') from None


def _validate(document):
    backend = document['backend_id']
    if backend not in ('deepseek', 'strata'):
        raise ValueError('unknown_backend')
    manifest = read(document['manifest_file'])
    template_file = Path(manifest['harnesses']['hermes']['config_file'])
    config = read(template_file)
    spec = config['profiles'].get(backend)
    if not isinstance(spec, dict):
        raise ValueError('unknown_backend')
    inherited = read(spec['template']) if spec.get('template') else {}
    provider = spec.get('provider') or inherited.get('model', {}).get('provider')
    source = Path(config['hermes_source']).resolve()
    if not isinstance(provider, str) or not provider.strip() or provider.strip().lower() in (_provider_ids(source) | {'auto', 'main', 'custom'}):
        raise ValueError('builtin_provider_collision')
    provider = provider.strip()
    entry = inherited.get('providers', {}).get(provider, {})
    if not entry:
        entry = next((row for row in inherited.get('custom_providers', []) if row.get('name') == provider), {})
    route = {key: entry[key] for key in ('base_url', 'api', 'api_mode', 'transport', 'model', 'key_cmd') if key in entry}
    route.update({key: spec[key] for key in ('base_url', 'api', 'api_mode', 'transport', 'model', 'key_cmd') if key in spec})
    default_model = spec.get('model') or inherited.get('model', {}).get('default') or route.get('model')
    backend_definition = manifest.get('backends', {}).get(backend, {})
    allowed_models = backend_definition.get('models', [backend_definition.get('model', default_model)])
    if not isinstance(allowed_models, list) or not allowed_models or not all(isinstance(row, str) and row for row in allowed_models):
        raise ValueError('model_mismatch')
    model = document.get('model')
    if not model or model not in allowed_models:
        raise ValueError('model_mismatch')
    helper = document.get('helper_model', 'same')
    if helper != 'same' and helper not in allowed_models:
        raise ValueError('invalid_helper_model')
    resume = document.get('resume_session_id')
    if resume is not None and (not isinstance(resume, str) or not resume.strip()
                               or resume.lower() == 'latest' or resume.startswith('-')):
        raise ValueError('invalid_resume_session_id')
    base = route.get('base_url') or route.get('api') or ''
    url = urlsplit(base)
    mode = route.get('api_mode') or route.get('transport')
    command = route.get('key_cmd')
    if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment
            or mode not in ('chat_completions', 'anthropic_messages')
            or not isinstance(command, str) or not shlex.split(command)):
        raise ValueError('invalid_route')
    if document.get('effort') is not None and document['effort'] not in EFFORTS:
        raise ValueError('invalid_effort')
    root = Path(config['managed_root']).resolve()
    install = root / 'installs' / hashlib.sha256(str(source).encode()).hexdigest()[:16]
    environment = Path(read(install / 'facts.json')['packages']['venv']['environment']).resolve()
    executable = environment / 'bin/hermes'
    python = environment / 'bin/python'
    if (not environment.is_relative_to((install / 'environments').resolve())
            or not (environment / 'pyvenv.cfg').is_file()
            or Path(config['hermes_executable']).resolve() != executable.resolve()
            or Path(config['hermes_python']).resolve() != python.resolve()
            or not all(os.access(path, os.X_OK) for path in (executable, python))):
        raise ValueError('invalid_runtime')
    product = Path(document['product_root']).resolve()
    if not (product / 'integrations/hermes/thin_guard.py').is_file():
        raise ValueError('invalid_runtime')
    route = {'base_url': base, 'api_mode': mode, 'key_cmd': command}
    # Explicit operator context is preserved; no guessed trial defaults/caps.
    context = spec.get('context_length', inherited.get('model', {}).get('context_length'))
    if context is not None:
        if type(context) is not int or context <= 0:
            raise ValueError('invalid_route')
        route['context_length'] = context
    return {'provider': provider, 'model': model, 'helper_model': model if helper == 'same' else helper,
            'route': route, 'source': str(source),
            'root': str(root), 'executable': str(executable), 'python': str(python),
            'profile': str(root / 'profiles' / backend), 'template_file': str(template_file),
            'credential_files': [str(template_file), *([str(Path(spec['template']).resolve())] if spec.get('template') else [])]}


def _save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _link(path, target):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() and path.resolve() == target.resolve():
        return
    if path.exists() or path.is_symlink():
        raise ValueError('owned_link_conflict')
    path.symlink_to(target)


@contextmanager
def _profile_lock(profile):
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (profile / '.orrery-thin.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _auxiliary_tasks(source):
    tree = ast.parse((source / 'hermes_cli/config_defaults.py').read_text())
    defaults = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'DEFAULT_CONFIG' for t in node.targets))
    auxiliary = next(value for key, value in zip(defaults.keys, defaults.values)
                     if isinstance(key, ast.Constant) and key.value == 'auxiliary')
    return [key.value for key, value in zip(auxiliary.keys, auxiliary.values)
            if isinstance(key, ast.Constant) and isinstance(value, (ast.Dict, ast.Call))]


def _personality_prompt(existing, source):
    """Read native personality data without importing the CLI or executing code."""
    name = str(existing.get('display', {}).get('personality') or '').strip().lower()
    if name in ('', 'none', 'default', 'neutral'):
        return ''
    tree = ast.parse((source / 'hermes_cli/personality.py').read_text())
    builtin = next(node.value for node in tree.body if isinstance(node, ast.AnnAssign)
                   and isinstance(node.target, ast.Name) and node.target.id == 'BUILTIN_PERSONALITIES')
    choices = ast.literal_eval(builtin)
    choices.update(existing.get('personalities') or {})
    choices.update(existing.get('agent', {}).get('personalities') or {})
    value = choices.get(name, '')
    if isinstance(value, dict):
        return '\n'.join(str(item).strip() for item in [value.get('system_prompt', ''),
            'Tone: ' + str(value['tone']) if value.get('tone') else '',
            'Style: ' + str(value['style']) if value.get('style') else ''] if str(item).strip())
    return str(value or '').strip()


def generate(document):
    facts = validate_input(document)
    product, profile = Path(document['product_root']).resolve(), Path(facts['profile'])
    pin = document.get('native_profile_env')
    if pin is not None and (not isinstance(pin, dict) or set(pin) != {'HERMES_HOME'}
                            or not isinstance(pin['HERMES_HOME'], str)
                            or Path(pin['HERMES_HOME']).resolve() != profile.resolve()):
        raise ValueError('native_resume_profile_changed')
    state, cwd = Path(document['state_dir']).resolve(), Path(document['cwd']).resolve()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', document['agent_name']) or not cwd.is_dir():
        raise ValueError('invalid_input')
    if document.get('worktree') and Path(document['worktree']).resolve() != cwd:
        raise ValueError('invalid_input')
    servers = read(document['mcp_config'])['mcpServers']
    if not isinstance(servers, dict):
        raise ValueError('unsupported_mcp_selection')
    selection = document.get('mcp_selection', {'inherit': True})
    instructions = Path(document['instructions_file']).read_text(encoding='utf-8')
    prompt = Path(document['prompt_file'])
    prompt_text = prompt.read_text(encoding='utf-8')
    with _profile_lock(profile):
        existing = read(profile / 'config.yaml') if (profile / 'config.yaml').exists() else {}
        enabled = existing.get('plugins', {}).get('enabled', [])
        if not isinstance(enabled, list):
            raise ValueError('inherited_mcp_conflict')
        if selection.get('inherit') is False and any(name != PLUGIN for name in enabled):
            # Portable plugins can append MCP servers after config is loaded.
            # No plugin import/preflight or silent expansion of the selection.
            raise ValueError('inherited_mcp_conflict')
        mcp = dict(servers)
        if selection.get('inherit') is False:
            for name in existing.get('mcp_servers', {}):
                if name not in mcp:
                    mcp[name] = {'enabled': False}
        plugin = profile / 'plugins' / PLUGIN
        plugin.mkdir(parents=True, exist_ok=True, mode=0o700)
        manifest = {'name': PLUGIN, 'version': '1.0.0', 'description': 'Common ORRERY native tool guards',
                    'provides_hooks': ['pre_tool_call', 'post_tool_call', 'on_session_start']}
        if (plugin / 'plugin.yaml').exists() and read(plugin / 'plugin.yaml') != manifest:
            raise ValueError('owned_link_conflict')
        _save(plugin / 'plugin.yaml', manifest)
        _link(plugin / '__init__.py', product / 'integrations/hermes/thin_guard.py')
        skills = Path(document.get('skills_root') or product / 'skills').resolve()
        for source in skills.glob('*/SKILL.md'):
            _link(profile / 'skills' / source.parent.name, source.parent)
        overlay = {
            'providers': {facts['provider']: facts['route']},
            'display': {'busy_input_mode': 'queue'},
            'agent': {'system_prompt': '\n\n'.join(filter(None, [existing.get('agent', {}).get('system_prompt'), instructions]))},
            'auth': {'adopt_external_logins': False},
            'mcp_servers': mcp,
            'plugins': {'enabled': list(dict.fromkeys([*enabled, PLUGIN]))},
            'auxiliary': {task: {'provider': 'main', 'model': facts['helper_model'], 'fallback_chain': []}
                          for task in _auxiliary_tasks(Path(facts['source']))},
            'delegation': {'provider': facts['provider'], 'model': facts['helper_model']},
        }
        personality = _personality_prompt(existing, Path(facts['source']))
        _save(state / 'overlay/config.yaml', overlay)
    definitions = state / 'credential-references.json'
    _save(definitions, {'backends': {'hermes': {'auth_command': shlex.split(facts['route']['key_cmd'])}}})
    argv = [facts['executable'], 'chat', '--provider', facts['provider'], '--model', facts['model']]
    if document.get('effort') is not None:
        argv.extend(['--reasoning', document['effort']])
    if document.get('resume_session_id') is not None:
        argv.extend(['--resume', document['resume_session_id']])
    if prompt_text:
        argv.extend(['--query-file', str(prompt)])
    env = {'HERMES_HOME': str(profile), 'HERMES_MANAGED_DIR': str(state / 'overlay'),
           'AGENTSTACK_LLM_KEY_DEFINITIONS': str(definitions),
           'AGENTSTACK_NATIVE_SESSION_FILE': str(state / 'native-session.json'),
           'AGENTSTACK_LLM_KEY_FILES': json.dumps([str(state / 'overlay/config.yaml'),
                str(profile / 'config.yaml'), str(profile / '.env'), str(profile / 'auth.json'),
                *facts['credential_files'], str(definitions)])}
    if personality:
        # Native personality normally wins over agent.system_prompt. Its
        # official ephemeral override preserves it plus the shared block.
        env['HERMES_EPHEMERAL_SYSTEM_PROMPT'] = personality + '\n\n' + instructions
    return {'argv': argv, 'env': env, 'cwd': str(cwd), 'program': 'hermes',
            'native_entry': facts['executable'], 'config_dir': str(state / 'overlay'),
            'profile_home': str(profile), 'guard': {'plugin': str(plugin / '__init__.py'), 'contract': 1}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        _save(args.out, generate(read(args.input)))
    except Exception as error:
        allowed = {'unknown_backend', 'model_mismatch', 'invalid_effort', 'builtin_provider_collision',
                   'invalid_runtime', 'invalid_route', 'invalid_input', 'unsupported_mcp_selection',
                   'inherited_mcp_conflict', 'owned_link_conflict', 'invalid_helper_model',
                   'invalid_resume_session_id', 'native_resume_profile_changed'}
        reason = str(error) if str(error) in allowed else 'invalid_input'
        print('HERMES_THIN_CONFIG_ERROR=' + reason, file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
