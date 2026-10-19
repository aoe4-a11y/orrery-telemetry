import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {apply, payloadFor, saveSession, callHook} from '../integrations/dsh/orrery_tools.mjs';

function fixture(run) {
  const handlers = new Map();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-thin-tools-'));
  const config = {hooks_dir: root, cwd: root, state_dir: root, env: {AGENT_NAME: 'OwnChild'}};
  const ctx = {on: (name, fn) => handlers.set(name, fn), workingDirectory: {ensure: async () => path.join(root, 'changed-cwd')}};
  apply(ctx, config, run);
  return {root, config, handlers, clean: () => fs.rmSync(root, {recursive: true, force: true})};
}
const exec = {name: 'write', arguments: {file_path: 'work.txt', content: 'private content'}, agent: {session: {id: 'own-id'}}};

test('native relative edit resolves effective cwd and invokes common registration/reservation only', async () => {
  const calls = [];
  const f = fixture(async (file, payload, env) => {calls.push({file, payload, env}); return {ok: true};});
  try {
    assert.equal(await f.handlers.get('tools/pre-execute')(exec, () => 'NATIVE_ALLOWED'), 'NATIVE_ALLOWED');
    assert.deepEqual(calls.map(c => path.basename(c.file)), ['deny-llm-key-read.py', 'check-agent-registered.sh', 'check-file-reservation.sh']);
    assert.equal(calls[2].payload.tool_name, 'Write');
    assert.equal(calls[2].payload.cwd, path.join(f.root, 'changed-cwd'));
    assert.equal(calls[2].payload.session_id, 'own-id');
    assert.equal(calls[2].env.AGENT_NAME, 'OwnChild');
    assert.equal(calls[2].payload.tool_input.file_path, 'work.txt');
  } finally { f.clean(); }
});

test('common denial prevents the native body; key/read do not call reservation policy', async () => {
  const calls = [];
  const f = fixture(async file => {calls.push(path.basename(file)); return {ok: false, reason: 'common refusal'};});
  try {
    let ran = false;
    assert.deepEqual(await f.handlers.get('tools/pre-execute')({...exec, name: 'bash'}, () => {ran = true;}), {kind: 'deny', reason: 'common refusal'});
    assert.equal(ran, false);
    assert.deepEqual(calls, ['deny-llm-key-read.py']);
  } finally { f.clean(); }
});

test('successful edits use existing release hook; failures and non-edits do not release', async () => {
  const calls = [];
  const f = fixture(async (file, payload) => {calls.push({file, payload}); return {ok: true};});
  try {
    await f.handlers.get('tools/result')(exec, {isError: true});
    await f.handlers.get('tools/result')({...exec, name: 'read'}, {isError: false});
    assert.equal(calls.length, 0);
    await f.handlers.get('tools/result')(exec, {isError: false});
    assert.equal(path.basename(calls[0].file), 'release-file-reservation.sh');
    assert.deepEqual(calls[0].payload.tool_result, {success: true});
    assert.equal(JSON.stringify(calls[0]).includes('private result'), false);
  } finally { f.clean(); }
});

test('native tool set has no independent allowlist and unrelated tools keep native decisions', async () => {
  const f = fixture(async () => ({ok: true}));
  try {
    for (const name of ['search', 'subagent', 'web', 'mcp__orrery_mail__fetch_inbox'])
      assert.equal(await f.handlers.get('tools/pre-execute')({...exec, name}, () => name), name);
    assert.equal(payloadFor({...exec, name: 'edit'}, f.config).tool_name, 'Edit');
  } finally { f.clean(); }
});

test('two child session bindings are separate; save failure does not stop launch', () => {
  const a = fixture(async () => ({ok: true}));
  const b = fixture(async () => ({ok: true}));
  try {
    a.handlers.get('agent/created')({agent: {session: {id: 'A'}}});
    b.handlers.get('agent/created')({agent: {session: {id: 'B'}}});
    for (const [f, id] of [[a, 'A'], [b, 'B']]) {
      const row = JSON.parse(fs.readFileSync(path.join(f.root, 'native-session.json')));
      assert.equal(row.harness, 'dsh');
      assert.equal(row.native_session_id, id);
      assert.ok(row.created_at);
    }
    a.handlers.get('agent/created')({agent: {session: {id: 'SUBAGENT', header: {parentSession: 'A'}}}});
    assert.equal(JSON.parse(fs.readFileSync(path.join(a.root, 'native-session.json'))).native_session_id, 'A');
    assert.doesNotThrow(() => saveSession({session: {id: 'C'}}, {state_dir: '/not-present/never'}));
  } finally { a.clean(); b.clean(); }
});

test('real subprocess hook exit is observed without exposing stderr', async () => {
  const f = fixture(async () => ({ok: true}));
  try {
    const file = path.join(f.root, 'fake-hook.sh');
    fs.writeFileSync(file, '#!/bin/sh\ncat >/dev/null\necho PRIVATE_KEY_LIKE_TEXT >&2\nexit 2\n', {mode: 0o700});
    const result = await callHook(file, {tool_name: 'Read'});
    assert.equal(result.ok, false);
    assert.equal(result.reason, 'ORRERY hook denied: fake-hook.sh');
  } finally { f.clean(); }
});

const nativeRuntime = process.env.ORRERY_DSH_TEST_RUNTIME;
const nativeNode = process.env.ORRERY_DSH_TEST_NODE;
const skipNative = !nativeRuntime || !nativeNode ? 'explicit pinned native runtime and Node required' : false;

test('native CLI tool dispatch invokes common hooks; broken adapter leaves native tools running', {skip: skipNative}, async () => {
  const {spawnSync} = await import('node:child_process');
  const {pathToFileURL} = await import('node:url');
  for (const mode of ['loaded', 'broken']) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-native-tools-'));
    const save = (name, text, mode = 0o600) => {const file = path.join(root, name);fs.mkdirSync(path.dirname(file), {recursive: true});fs.writeFileSync(file, text, {mode});return file;};
    try {
      const home = path.join(root, 'dsh');
      const profile = path.join(home, 'profiles/probe');
      save('dsh/profiles/probe/package.json', JSON.stringify({name: 'native-tool-probe', private: true, dsh: {profile: {bundles: ['@deepseek-ai/dsh-base']}}}));
      save('dsh/profiles/probe/cordis.patch.yml', '[]');
      fs.symlinkSync(path.join(nativeRuntime, 'node_modules'), path.join(profile, 'node_modules'));
      const hooks = path.join(root, 'hooks');
      const realGuard = process.env.ORRERY_DSH_TEST_KEY_GUARD ?? path.resolve('hooks/deny-llm-key-read.py');
      fs.mkdirSync(hooks);
      fs.copyFileSync(realGuard, path.join(hooks, 'deny-llm-key-read.py'));
      fs.chmodSync(path.join(hooks, 'deny-llm-key-read.py'), 0o700);
      save('hooks/check-agent-registered.sh', '#!/bin/sh\ncat >/dev/null\nexit 0\n', 0o700);
      save('hooks/release-file-reservation.sh', '#!/bin/sh\ncat >/dev/null\nexit 0\n', 0o700);
      save('hooks/check-file-reservation.sh', '#!/bin/sh\ninput=$(cat)\ncase "$input" in *allowed.txt*) exit 0;; *) exit 2;; esac\n', 0o700);
      const secretHelper = save('security', '#!/bin/sh\necho CALLED >>"' + path.join(root, 'helper-calls') + '"\necho SYNTHETIC\n', 0o700);
      const definitions = save('backends.json', JSON.stringify({backends: {strata: {keychain: {service: 'fake-service', account: 'fake-account'}}}}));
      const protectedFile = save('provider-config.json', '{"not_a_real_key":true}');
      const plugin = mode === 'loaded' ? path.resolve('integrations/dsh/orrery_tools.mjs') : save('broken.mjs', 'throw new Error("BROKEN_ADAPTER")');
      const probe = save('probe.mjs', `import fs from 'node:fs';export const inject=['tools','agents'];export function apply(ctx,config){ctx.get('appReady').onReady(async()=>{
const rows=[];
try {
const handle=await ctx.agents.create({sessionId:'native-own-session',meta:{cwd:config.root}});
const child=await ctx.agents.create({sessionId:'native-delegated-session',meta:{cwd:config.root,parentSession:'native-own-session',origin:'subagent'},parentAgent:handle.agent});
const call=(name,args)=>handle.agent.ctx.tools.execute({callId:'probe-'+rows.length,name,agent:handle.agent,arguments:args,signal:new AbortController().signal});
 for(const file of ['unreserved.txt','expired.txt','conflict.txt','allowed.txt']) { const r=await call('write',{file_path:config.root+'/'+file,content:'native write'});rows.push({file,error:r.isError}); }
 if(config.mode==='loaded') {const read=await call('read',{file_path:config.protected});rows.push({file:'protected-read',error:read.isError});
 const shell=await call('bash',{command:config.helper+' find-generic-password -s fake-service -a fake-account -w',description:'synthetic guard probe'});rows.push({file:'key-helper',error:shell.isError});}
 fs.writeFileSync(config.root+'/result.json',JSON.stringify({rows,binding:fs.existsSync(config.root+'/native-session.json')?JSON.parse(fs.readFileSync(config.root+'/native-session.json')):null,tools:ctx.tools.schemas().map(r=>r.name)}));
}catch(error){fs.writeFileSync(config.root+'/result.json',JSON.stringify({error:error.message}));}
ctx.get('appExit')(0);});}`);
      const disabled = ['session-title-llm', 'session-log-deepseek', 'plugin-package-inventory-deepseek', 'session-telemetry-otel'];
      const patchFile = save('native.patch.json', JSON.stringify([
        ...disabled.map(id => ({id, disabled: true})),
        {insert: [{id: 'orrery-tools', name: plugin, config: {cwd: root, state_dir: root, hooks_dir: hooks, env: {}}},
          {id: 'native-probe', name: probe, config: {root, mode, protected: protectedFile, helper: secretHelper}}]},
      ]));
      const offline = save('offline.mjs', "globalThis.fetch=()=>{throw new Error('NETWORK_FORBIDDEN')};");
      const result = spawnSync(nativeNode, ['--import', offline, path.join(nativeRuntime, 'node_modules/@deepseek-ai/dsh/lib/bin.js'), '--profile', 'probe', '--patch', patchFile], {
        cwd: root, env: {HOME: root, DSH_HOME: home, PATH: path.dirname(nativeNode) + ':/usr/bin:/bin', LANG: 'en_US.UTF-8', DSH_TELEMETRY_DISABLED: '1',
          AGENTSTACK_LLM_KEY_DEFINITIONS: definitions, AGENTSTACK_LLM_KEY_FILES: JSON.stringify([protectedFile])}, encoding: 'utf8', timeout: 45000});
      assert.equal(result.error, undefined, result.stdout + result.stderr);
      assert.equal(result.status, 0, result.stdout + result.stderr);
      const evidence = JSON.parse(fs.readFileSync(path.join(root, 'result.json')));
      assert.equal(evidence.error, undefined, JSON.stringify(evidence) + result.stdout + result.stderr);
      assert.ok(evidence.tools.includes('write'));
      for (const file of ['unreserved.txt', 'expired.txt', 'conflict.txt'])
        assert.equal(fs.existsSync(path.join(root, file)), mode === 'broken', JSON.stringify(evidence));
      assert.equal(fs.readFileSync(path.join(root, 'allowed.txt'), 'utf8'), 'native write');
      if (mode === 'loaded') {
        assert.equal(evidence.binding.native_session_id, 'native-own-session');
        assert.equal(evidence.binding.harness, 'dsh');
        assert.equal(fs.existsSync(path.join(root, 'helper-calls')), false);
        assert.equal(evidence.rows.find(row => row.file === 'protected-read').error, true);
        assert.equal(evidence.rows.find(row => row.file === 'key-helper').error, true);
      }
      console.log(JSON.stringify({mode, native_tool_dispatch: true, ...evidence}));
    } finally {fs.rmSync(root, {recursive: true, force: true});}
  }
});
