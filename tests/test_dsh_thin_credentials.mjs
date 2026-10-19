// Real native CLI, private HOME, synthetic security, no provider/network traffic.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {providerClass} from '../integrations/dsh/keychain_credentials.mjs';

const INIT = Symbol('init');
class Local {
  static calls = 0;
  async *[INIT]() {}
  async resolve() {Local.calls++; return {value: 'ambient-canary'};}
  async describe() {return {writable: true};}
  async write() {throw new Error('should not persist selected ref');}
}

test('one memory lookup, no selected env/file fallback or persistence, failure cached', async () => {
  let calls = 0;
  const Provider = providerClass(Local, {init: INIT}, {ref: 'selected'}, async () => {calls++; return 'memory-fixture';});
  const p = new Provider({});
  assert.equal((await p.resolve('selected')).value, 'memory-fixture');
  assert.equal((await p.resolve('selected')).value, 'memory-fixture');
  assert.equal(calls, 1);
  assert.equal(Local.calls, 0);
  await assert.rejects(p.write('selected', 'anything'), /READ_ONLY/);
  assert.equal((await p.describe('selected')).writable, false);
  await p.resolve('other');
  assert.equal(Local.calls, 1);
  calls = 0;
  const Bad = providerClass(Local, {init: INIT}, {ref: 'selected'}, async () => {calls++; throw new Error('private stderr');});
  const bad = new Bad({});
  for (let i = 0; i < 2; i++) await assert.rejects(bad.resolve('selected'), /^Error: DSH_KEYCHAIN_UNAVAILABLE$/);
  assert.equal(calls, 1);
});

const runtime = process.env.ORRERY_DSH_TEST_RUNTIME;
const node = process.env.ORRERY_DSH_TEST_NODE;
const nativeSkip = !runtime || !node ? 'explicit pinned native runtime and Node required' : false;
const plugin = pathToFileURL(path.resolve('integrations/dsh/keychain_credentials.mjs')).href;

function nativeCase(mode) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-native-key-'));
  const save = (name, data) => {const file = path.join(root, name); fs.mkdirSync(path.dirname(file), {recursive: true}); fs.writeFileSync(file, data, {mode: 0o600}); return file;};
  const profile = path.join(root, 'dsh/profiles/probe');
  save('dsh/profiles/probe/package.json', JSON.stringify({name: 'offline-probe', private: true, dsh: {profile: {bundles: []}}}));
  fs.symlinkSync(path.join(runtime, 'node_modules'), path.join(profile, 'node_modules'));
  save('dsh/profiles/probe/cordis.patch.yml', '[]');
  const selected = 'ORRERY_DSH_PROVIDER_KEY';
  save('dsh/.credentials.yaml', 'version: 1\nrefs:\n  ' + selected + ': "FILE_CANARY"\n  DEEPSEEK_API_KEY: "OTHER_FILE_CANARY"\n');
  const originalCredentials = fs.readFileSync(path.join(root, 'dsh/.credentials.yaml'), 'utf8');
  const fakeSecurity = save('security.mjs', `import fs from 'node:fs';fs.appendFileSync(${JSON.stringify(path.join(root, 'security-calls'))}, 'lookup\\n');${mode === 'lookup-failure' ? 'process.exit(1);' : "process.stdout.write('MEMORY_FIXTURE_KEY');"}`);
  const credentialWrapper = save('credential-wrapper.mjs', `import {execFile} from 'node:child_process';import {install} from ${JSON.stringify(plugin)};
export async function apply(ctx, config) { await install(ctx, config, () => new Promise((resolve,reject)=>execFile(${JSON.stringify(node)},[${JSON.stringify(fakeSecurity)}],{encoding:'utf8'},(err,out)=>err?reject(err):resolve(out)))); }`);
  const probe = save('probe.mjs', `import fs from 'node:fs';export function apply(ctx, config) {
ctx.get('appReady').onReady(async () => { const out = {native_process:true, credentials_loaded:!!ctx.get('credentials'), adapter_loaded:ctx.get('llm').adapters.has('deepseek-official'), auth_ok:false, canary_used:false, network_requests:globalThis.__networkRequests??0};
try { const adapter = ctx.get('llm').adapters.get('deepseek-official')?.adapter;
if(adapter) { const auth = await adapter.dependencies.resolveAuth({apiKeyEnv:${JSON.stringify(selected)}}); out.auth_ok=auth.headers['x-api-key']==='MEMORY_FIXTURE_KEY';out.canary_used=auth.headers['x-api-key'].includes('CANARY'); }
const creds=ctx.get('credentials'); if(creds && out.auth_ok) {out.memory_twice=(await creds.resolve(${JSON.stringify(selected)})).value==='MEMORY_FIXTURE_KEY';try {await creds.set(${JSON.stringify(selected)},'persist-attempt');}catch{out.write_denied=true;} }
} catch(error) {out.auth_failed=true;out.error_type=error.name;out.error_message=error.message;}
fs.writeFileSync(config.result,JSON.stringify(out));ctx.get('appExit')(0); }); }`);
  const guard = save('offline.mjs', "globalThis.__networkRequests=0;globalThis.fetch=()=>{globalThis.__networkRequests++;throw new Error('NETWORK_FORBIDDEN')};");
  const rows = [
    {id: 'llm', name: '@deepseek-ai/dsh-llm'},
    {id: 'credentials', name: mode === 'missing' ? path.join(root, 'absent.mjs') : mode === 'import-failure' ? save('broken.mjs', 'throw new Error("BROKEN_PLUGIN")') : credentialWrapper,
      disabled: mode === 'disabled', config: {runtime, dshHome: path.join(root, 'dsh'), ref: selected, service: 'fake-service', account: 'fake-account'}},
    {id: 'llm-provider', name: '@deepseek-ai/dsh-llm-deepseek-api-key', inject: ['llm', 'credentials'], config: {baseURL: 'https://provider.invalid', apiKeyEnv: selected}},
    {id: 'probe', name: probe, inject: ['llm'], config: {result: path.join(root, 'result.json')}},
  ];
  save('patch.json', JSON.stringify([{insert: rows}]));
  const result = spawnSync(node, ['--import', guard, path.join(runtime, 'node_modules/@deepseek-ai/dsh/lib/bin.js'), '--profile', 'probe', '--patch', path.join(root, 'patch.json')],
    {cwd: root, env: {HOME: root, DSH_HOME: path.join(root, 'dsh'), PATH: path.dirname(node) + ':/usr/bin:/bin', LANG: 'en_US.UTF-8',
      DEEPSEEK_API_KEY: 'ENV_CANARY', ORRERY_DSH_PROVIDER_KEY: 'SELECTED_ENV_CANARY', DSH_TELEMETRY_DISABLED: '1'}, encoding: 'utf8', timeout: 30000});
  let evidence;
  try {
    if (fs.existsSync(path.join(root, 'result.json'))) evidence = JSON.parse(fs.readFileSync(path.join(root, 'result.json')));
    const calls = fs.existsSync(path.join(root, 'security-calls')) ? fs.readFileSync(path.join(root, 'security-calls'), 'utf8').trim().split('\n').length : 0;
    assert.equal(result.error, undefined, 'native CLI timed out: ' + result.stdout + result.stderr);
    assert.equal(fs.readFileSync(path.join(root, 'dsh/.credentials.yaml'), 'utf8'), originalCredentials);
    assert.equal((result.stdout + result.stderr).includes('MEMORY_FIXTURE_KEY'), false);
    assert.equal((result.stdout + result.stderr).includes('SELECTED_ENV_CANARY'), false);
    if (mode === 'ok') {
      assert.equal(result.status, 0, result.stderr);
      assert.ok(evidence?.credentials_loaded, JSON.stringify(evidence) + result.stdout + result.stderr);
      assert.ok(evidence.auth_ok, JSON.stringify(evidence) + result.stdout + result.stderr);
      assert.ok(evidence.memory_twice);
      assert.ok(evidence.write_denied);
      assert.equal(calls, 1);
      assert.equal(evidence.network_requests, 0);
    } else {
      assert.equal(evidence?.network_requests ?? 0, 0);
      assert.equal(evidence?.canary_used ?? false, false);
      assert.equal(evidence?.auth_ok ?? false, false);
      assert.equal(calls, mode === 'lookup-failure' ? 1 : 0);
      assert.ok(evidence || result.status !== 0, 'negative did not run probe or fail visibly: ' + result.stderr);
    }
    return {mode, exit: result.status, evidence, security_calls: calls};
  } finally { fs.rmSync(root, {recursive: true, force: true}); }
}

test('native CLI loads memory credentials; absent/disabled/import/lookup cannot fall back to canaries', {skip: nativeSkip}, () => {
  for (const mode of ['ok', 'missing', 'disabled', 'import-failure', 'lookup-failure']) {
    const row = nativeCase(mode);
    console.log(JSON.stringify(row));
  }
});
