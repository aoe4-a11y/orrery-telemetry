#!/usr/bin/env python3
"""Non-secret config helpers for the standard native harness launcher."""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

if __package__:
    from . import child_resume, child_tools
else:
    import child_resume
    import child_tools

ROOT = Path(__file__).resolve().parents[1]
HARNESSES = {'dsh', 'hermes'}
BACKENDS = {'deepseek', 'strata'}
_VALIDATION_CACHE = {}
VALIDATION_CACHE_SECONDS = 15


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    child_resume._atomic_json(Path(path), value)


def config_generator(root, harness):
    file = Path(root) / 'integrations' / harness / 'thin_config.py'
    try:
        tree = ast.parse(file.read_text())
        declared = any(isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == 'THIN_CONFIG_CONTRACT'
            for target in node.targets) and isinstance(node.value, ast.Constant)
            and type(node.value.value) is int and node.value.value == 1 for node in tree.body)
    except (OSError, SyntaxError):
        declared = False
    if not declared:
        raise ValueError('thin_config_unavailable')
    return file


def static_check(receipt, config, *, harness):
    """Shared catalog/launcher check; no provider imports, key reads or RPC."""
    try:
        if (receipt.get('variant') != 'plain' or type(receipt.get('thin_config_contract')) is not int or receipt['thin_config_contract'] != 1
                or receipt.get('harness') != harness or receipt.get('complete') is not True):
            return dict(available=False, reason='plain_generation_required')
        config_generator(ROOT, harness)
        details = receipt['details']
        required = ('node','runtime') if harness == 'dsh' else ('hermes_executable','hermes_source','managed_root')
        for key in required:
            value = config[key]
            if value != details[key] or not Path(value).is_absolute() or not Path(value).exists():
                return dict(available=False, reason='runtime_not_prepared')
        executable = config['node' if harness == 'dsh' else 'hermes_executable']
        if not os.access(executable, os.X_OK):
            return dict(available=False, reason='runtime_not_prepared')
        if harness == 'dsh':
            if config.get('patch_receipt'):
                return dict(available=False, reason='plain_generation_required')
            pins = read(ROOT / 'integrations/dsh/runtime-pins.json')
            for pin in pins:
                metadata = Path(config['runtime']) / 'node_modules' / pin['name'] / 'package.json'
                if read(metadata).get('version') != pin['version']:
                    return dict(available=False, reason='runtime_version_mismatch')
        return dict(available=True, reason=None)
    except (OSError, ValueError, KeyError, TypeError):
        return dict(available=False, reason='runtime_not_prepared')


def selection(manifest, harness, backend, model, effort=None):
    if harness not in HARNESSES or backend not in BACKENDS or not model:
        raise ValueError('invalid_harness_selection')
    config_generator(ROOT, harness)
    if not manifest:
        raise ValueError('harness_not_enabled')
    data = read(manifest)
    if data.get('enabled') is not True:
        raise ValueError('harness_not_enabled')
    backend_spec = data.get('backends', {}).get(backend, {})
    models = backend_spec.get('models', [backend_spec.get('model')])
    if not isinstance(models,list) or not models or not all(isinstance(v,str) and v for v in models):
        raise ValueError('invalid_model_catalog')
    if model not in models:
        raise ValueError('model_mismatch')
    runner = data['harnesses'][harness]
    if not Path(runner['python']).is_absolute() or not Path(runner['config_file']).is_absolute():
        raise ValueError('runtime_not_prepared')
    template = read(runner['config_file'])
    check = static_check(read(template['generation_receipt']), template, harness=harness)
    if not check['available']:
        raise ValueError(check['reason'])
    document = dict(manifest_file=str(Path(manifest).resolve()), product_root=str(ROOT),
                    backend_id=backend, model=model)
    if effort is not None:
        document['effort'] = effort
    code = ('import importlib.util,json,sys,re; '
            's=importlib.util.spec_from_file_location("orrery_thin_validation",sys.argv[1]); '
            'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
            '\ntry:m.validate_input(json.loads(sys.argv[2]))'
            '\nexcept ValueError as e: print(str(e) if re.fullmatch(r"[a-z_]+",str(e)) else "invalid_runtime");sys.exit(2)')
    generator = config_generator(ROOT,harness)
    files = [manifest,runner['config_file'],template['generation_receipt'],generator,
             template.get('backend_file'),template.get('profiles',{}).get(backend,{}).get('template'),
             ROOT / 'integrations' / harness / ('orrery_tools.mjs' if harness=='dsh' else 'thin_guard.py')]
    fingerprints = []
    for file in files:
        if not file:
            continue
        try:
            info=Path(file).stat()
            fingerprints.append((str(file),info.st_mtime_ns,info.st_size))
        except OSError:
            fingerprints.append((str(file),None,None))
    signature = tuple(fingerprints)
    key = (str(manifest),harness,backend,model,effort)
    cached = _VALIDATION_CACHE.get(key)
    if cached and cached[0] == signature and time.monotonic()-cached[1] < VALIDATION_CACHE_SECONDS:
        reason = cached[2]
    else:
        try:
            result = subprocess.run([runner['python'], '-I', '-B', '-c', code,
                str(generator), json.dumps(document)], capture_output=True, text=True, timeout=5)
            reason = None
            if result.returncode:
                text=result.stdout.strip()
                reason=text if re.fullmatch(r'[a-z_]+',text) else 'runtime_not_prepared'
        except subprocess.TimeoutExpired:
            reason = 'validate_timeout'
        _VALIDATION_CACHE[key] = (signature,time.monotonic(),reason)
    if reason:
        raise ValueError(reason)
    return runner


def prepare(args):
    if not re.fullmatch(r'[0-9a-f]{32}', args.generation):
        raise ValueError('invalid_registration_generation')
    runtime = Path(args.runtime_dir).resolve()
    child_file = runtime / 'child-agents' / (args.agent_name + '.json')
    state = child_resume._load_state(child_file)
    child_resume._validate_identity(state, agent_name=args.agent_name,
                                   project_key=args.project_key, program=args.harness)
    if not child_resume._registration_matches(
            child_file.with_name('.' + args.agent_name + '.registration-pending.json'), args.generation):
        raise ValueError('registration_attempt_changed')
    runner = selection(args.manifest, args.harness, args.backend, args.model, args.effort)
    state_dir = child_file.parent / (args.agent_name + '.harness') / args.generation
    state_dir.mkdir(parents=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    prompt = state_dir / 'initial-prompt.txt'
    child_resume._atomic_bytes(prompt, Path(args.prompt_file).read_bytes())
    spec = importlib.util.spec_from_file_location('harness_instruction_blocks', ROOT / 'bin/lib/instruction_blocks.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    instructions = state_dir / 'instructions.md'
    child_resume._atomic_bytes(instructions, renderer.render(
        'codex', (ROOT / 'codex/AGENTS.md').read_bytes(), str(ROOT), args.project_key))
    document = dict(agent_name=args.agent_name, program=args.harness, backend_id=args.backend,
        model=args.model, project_key=args.project_key, cwd=str(Path(args.cwd).resolve()),
        parent_agent=args.parent_agent or None, product_root=str(ROOT), runtime_dir=str(runtime),
        state_dir=str(state_dir), mcp_config=str(Path(args.mcp_config).resolve()),
        prompt_file=str(prompt), instructions_file=str(instructions),
        manifest_file=str(Path(args.manifest).resolve()), tools=json.loads(args.tools),
        env=dict(AGENT_NAME=args.agent_name, AGENTSTACK_HOME=str(ROOT),
                 AGENTSTACK_RUNTIME_DIR=str(runtime), AGENTSTACK_PROJECT_KEY=args.project_key))
    document['mcp_selection'] = child_tools.native_plan(document['tools'], cwd=document['cwd'],
        claude_json=os.environ.get('AGENTSTACK_CLAUDE_JSON',str(Path.home()/'.claude.json')))
    merged_mcp = read(document['mcp_config'])
    merged_mcp['mcpServers'].update(document['mcp_selection']['servers'])
    selected_mcp = state_dir / 'selected-mcp.json'
    save(selected_mcp, merged_mcp)
    document['mcp_config'] = str(selected_mcp)
    if getattr(args,'helper_model',None) not in (None,'','same'):
        document['helper_model'] = args.helper_model
    if args.effort is not None:
        document['effort'] = args.effort
    source, output = state_dir / 'input.json', state_dir / 'launch.json'
    save(source, document)
    result = subprocess.run([runner['python'], '-B', str(config_generator(ROOT,args.harness)),
        '--input', str(source), '--out', str(output)], capture_output=True, text=True)
    if result.returncode:
        reason = re.search(r'^(?:DSH|HERMES)_THIN_CONFIG_ERROR=([a-z_]+)$', result.stderr.strip())
        raise ValueError(reason[1] if reason else 'thin_config_generation_failed')
    plan = read(output)
    validate_plan(plan, document['cwd'])
    state.update(harness=args.harness, harness_backend=args.backend, harness_state_dir=str(state_dir))
    save(child_file, state)
    return state_dir


def validate_plan(plan, cwd):
    argv, env = plan.get('argv'), plan.get('env', {})
    if (not isinstance(argv, list) or not argv or
            not all(isinstance(arg, str) and '\0' not in arg for arg in argv) or
            not Path(argv[0]).is_absolute() or plan.get('cwd') != cwd):
        raise ValueError('invalid_native_launch_plan')
    if not isinstance(env, dict) or not all(isinstance(k,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',k)
            and isinstance(v,str) and '\0' not in v for k,v in env.items()):
        raise ValueError('invalid_native_environment')
    # Config generators return references only. Credentials are acquired by the CLI.
    if any(k.endswith(('_API_KEY','_REGISTRATION_TOKEN')) or k in ('CHILD_REGISTRATION_TOKEN','MCP_AGENT_MAIL_TOKEN') for k in env):
        raise ValueError('credential_value_in_launch_plan')


def command(state_dir, name):
    import shlex
    source = read(Path(state_dir) / 'input.json')
    if source['agent_name'] != name:
        raise ValueError('native_identity_mismatch')
    plan = read(Path(state_dir) / 'launch.json')
    validate_plan(plan, source['cwd'])
    invocation = shlex.join(['env', *[k+'='+v for k,v in plan.get('env', {}).items()], *plan['argv']])
    cleanup = shlex.join(['/bin/bash', str(ROOT / 'hooks/cleanup-child-agent.sh'), name])
    # Same lifetime and exit cleanup as native Codex; no ORRERY runtime wrapper.
    # Record native termination before slow/unreachable Mail cleanup can keep
    # its pane shell alive. This is not a task or turn completion receipt.
    marker = shlex.quote(str(Path(state_dir) / 'native-exit.status'))
    return (invocation + '; native_rc=$?; marker_rc=0; printf "%s\\n" "$native_rc" > ' + marker +
            ' || marker_rc=1; ' + cleanup +
            ' || exit $?; test "$marker_rc" = 0 || exit "$marker_rc"; exit "$native_rc"')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate', 'prepare', 'command'))
    for key in ('harness', 'backend', 'model', 'effort', 'manifest', 'runtime-dir', 'agent-name',
                'project-key', 'generation', 'cwd', 'parent-agent', 'mcp-config', 'prompt-file', 'state', 'helper-model'):
        parser.add_argument('--' + key)
    parser.add_argument('--tools', default='{"base":"default","tools":{}}')
    args = parser.parse_args()
    try:
        if args.action == 'validate':
            selection(args.manifest, args.harness, args.backend, args.model, args.effort)
        elif args.action == 'prepare':
            print(prepare(args))
        else:
            print(command(args.state, args.agent_name))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        reason = str(error) if re.fullmatch(r'[a-z_]+', str(error)) else type(error).__name__
        if isinstance(error, child_tools.ToolsError):
            reason = 'unsupported_mcp_selection'
        print('Harness ' + args.action + ' failed: ' + reason, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
