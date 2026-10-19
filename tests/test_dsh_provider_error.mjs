// Offline provider failures only: no sockets, registrations, or real keys.
import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {safeErrorText, providerError} from '../integrations/dsh/provider_error.mjs';

const secret = 'fixture-real-value-must-never-be-saved';
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-error-fixture-'));
const spec = JSON.parse(fs.readFileSync(path.join(project, 'integrations/dsh/backend.json')));
for (const [id, backend] of Object.entries(spec.backends)) {
  backend.base_url = 'https://' + id + '.invalid';
  backend.idle_check = false;
}
const backendFile = path.join(root, 'backends.json');
fs.writeFileSync(backendFile, JSON.stringify(spec));
fs.writeFileSync(path.join(root, 'attempt.json'), JSON.stringify({attempt_id: 'fixture-error', phase: 'run'}));
Object.assign(process.env, {ORRERY_DSH_STATE_ROOT: root, ORRERY_DSH_AUDIT_FILE: path.join(root, 'audit.jsonl'),
  ORRERY_DSH_BACKEND_FILE: backendFile, ORRERY_DSH_BACKEND_ID: 'strata', ORRERY_DSH_ATTEMPT_ID: 'fixture-error',
  ORRERY_DSH_OFFLINE: '1', DEEPSEEK_API_KEY: secret});
const {createEgress} = await import('../integrations/dsh/egress.mjs');
after(() => fs.rmSync(root, {recursive: true, force: true}));

function fixture(response, id = 'strata') {
  const audit = [], calls = [], backend = spec.backends[id];
  const fetch = createEgress({backend, limits: spec.limits, wireTools: spec.wire_tools, offline: false,
    key: secret, audit: row => audit.push(row), fetchImpl: async (input, init) => {
      calls.push({url: String(input), body: JSON.parse(init.body)});
      return response;
    }});
  const request = () => fetch(backend.base_url + '/v1/messages', {method: 'POST',
    body: JSON.stringify({model: backend.model, max_tokens: 256000,
      tools: spec.wire_tools.map(name => ({name})), messages: [{role: 'user', content: 'PRIVATE PROMPT'}]})});
  return {audit, calls, request};
}

test('structured context errors retain safe type/code/message prefix', async () => {
  const row = await providerError(Response.json({error: {type: 'invalid_request_error',
    code: 'context_length_exceeded', message: 'prompt (1183) + max tokens (256000) exceeds context (131072)'}}));
  assert.equal(row.type, 'invalid_request_error');
  assert.equal(row.code, 'context_length_exceeded');
  assert.match(row.message_prefix, /256000/);
});

test('mask the real credential and common key formats before truncation', async () => {
  const keys = [secret, 'sk-ant-abcdefghijk12345', 'Bearer abcdefghijk', 'api_key=abcdefghijk',
    '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'];
  const row = await providerError(Response.json({error: {type: secret, code: secret,
    message: keys.join(' ') + '\n\x1b[31mcontext mismatch\x1b[0m'}}), secret);
  for (const key of keys) assert.ok(!JSON.stringify(row).includes(key));
  assert.ok(!row.message_prefix.includes('\n'));
  assert.ok(!row.message_prefix.includes('\x1b'));
  const bounded = safeErrorText('safe '.repeat(45) + secret + ' ' + 'tail '.repeat(100), secret);
  assert.ok(bounded.length <= 240);
  assert.ok(!bounded.includes('fixture-real'));
});

test('ignore generated output, headers and other raw response fields', async () => {
  const row = await providerError(Response.json({error: {type: 'provider_error', message: 'safe',
    details: 'PRIVATE MODEL OUTPUT'}, choices: [{text: 'PRIVATE MODEL OUTPUT'}],
    content: [{text: 'PRIVATE MODEL OUTPUT'}], private: secret}, {headers: {'x-private': secret}}), secret);
  assert.equal(row.message_prefix, 'safe');
  assert.ok(!JSON.stringify(row).includes('PRIVATE'));
  assert.ok(!JSON.stringify(row).includes(secret));
  const noError = await providerError(Response.json({content: [{text: 'PRIVATE MODEL OUTPUT'}]}), secret);
  assert.equal(noError.available, false);
  assert.ok(!JSON.stringify(noError).includes('PRIVATE'));
});

test('malformed JSON, null and non-scalar error fields preserve failure without raw payload', async () => {
  for (const value of [new Response('<html>PRIVATE MODEL OUTPUT</html>'), Response.json(null),
    Response.json({error: []}), Response.json({error: {type: {}, code: [], message: {private: secret}}})]) {
    const row = await providerError(value, secret);
    assert.ok(!JSON.stringify(row).includes(secret));
    assert.ok(!JSON.stringify(row).includes('PRIVATE'));
  }
  const row = await providerError(Response.json({error: {code: 400, message: 'request rejected'}}));
  assert.equal(row.code, '400');
});

test('400/500 retain sent max_tokens and stay fatal on both backends; no count or retry', async () => {
  for (const id of ['strata', 'deepseek']) for (const status of [400, 500]) {
    const h = fixture(Response.json({error: {type: 'invalid_request_error', code: 'context_length_exceeded',
      message: 'prompt + max tokens (256000) exceeds context; ' + secret}, content: 'PRIVATE MODEL OUTPUT'}, {status}), id);
    await assert.rejects(h.request(), /DSH_PROVIDER/);
    const row = h.audit.find(row => row.phase === 'provider-response');
    assert.equal(row.status, status);
    assert.equal(row.max_tokens, 256000);
    assert.equal(row.error.code, 'context_length_exceeded');
    assert.equal(h.calls[0].body.max_tokens, 256000);
    assert.equal(h.audit.find(row => row.phase === 'stream-end').ok, false);
    assert.ok(!JSON.stringify(h.audit).includes(secret));
    assert.ok(!JSON.stringify(h.audit).includes('PRIVATE'));
    await assert.rejects(h.request(), /DSH_USAGE_UNKNOWN/);
    assert.equal(h.calls.length, 1);
    assert.ok(h.calls[0].url.endsWith('/v1/messages'));
  }
});

test('non-JSON provider failures still record status and sent max_tokens', async () => {
  const h = fixture(new Response('PRIVATE ERROR PAGE ' + secret, {status: 503}));
  await assert.rejects(h.request(), /DSH_PROVIDER/);
  const row = h.audit.find(row => row.phase === 'provider-response');
  assert.equal(row.status, 503);
  assert.equal(row.max_tokens, 256000);
  assert.equal(row.error.reason, 'structured_error_unreadable');
  assert.ok(!JSON.stringify(h.audit).includes('PRIVATE'));
});

test('200 generated output is not included in provider response audit', async () => {
  const h = fixture(new Response('data: {"type":"content_block_delta","delta":{"text":"PRIVATE MODEL OUTPUT"}}\n\n' +
    'data: {"type":"message_delta","usage":{"input_tokens":1,"cache_read_input_tokens":0,"output_tokens":1}}\n\n'));
  assert.match(await (await h.request()).text(), /PRIVATE MODEL OUTPUT/);
  const row = h.audit.find(row => row.phase === 'provider-response');
  assert.equal(row.status, 200);
  assert.equal(row.error, undefined);
  assert.ok(!JSON.stringify(h.audit).includes('PRIVATE'));
});
