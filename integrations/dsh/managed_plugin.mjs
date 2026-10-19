// Ordinary path mistakes/expired reservations can touch live files. Deny in
// the registry's monotonic guard, not the TUI's fail-open DecisionEvents.
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {unwrap, normalizeReservations} from './mail_probe.mjs';

export const name = 'orrery-dsh-managed';
export const inject = ['tools', 'systemPrompt', 'loader'];
const MAIL = 'mcp__orrery_mail__send_message';
const digest = p => createHash('sha256').update(fs.readFileSync(p)).digest('hex');

function contained(root, target) {
  const relative = path.relative(root, target);
  return relative !== '..' && !relative.startsWith('../') && !path.isAbsolute(relative);
}

export function canonicalTarget(root, supplied) {
  // A TUI workspace/cwd change must not retarget a checked relative path.
  if (typeof supplied !== 'string' || !path.isAbsolute(supplied) || supplied.includes('\0')) return null;
  let ancestor = path.resolve(supplied);
  const suffix = [];
  try {
    while (!fs.existsSync(ancestor)) {
      try { if (fs.lstatSync(ancestor).isSymbolicLink()) return null; }
      catch (error) { if (error.code !== 'ENOENT') return null; }
      suffix.unshift(path.basename(ancestor));
      ancestor = path.dirname(ancestor);
    }
    const target = path.join(fs.realpathSync(ancestor), ...suffix);
    if (!contained(root, target) || path.relative(root, target).split(path.sep).includes('.git')) return null;
    return target;
  } catch { return null; }
}

function matches(relative, pattern) {
  return typeof pattern === 'string' && !path.isAbsolute(pattern) &&
    !pattern.split('/').includes('..') && path.matchesGlob(relative, pattern);
}

export function createReservationGuard({attempt, task, emit, now = Date.now, wireTools}) {
  const root = fs.realpathSync(task.worktree);
  const allowed = new Set(attempt.phase === 'spike' ? ['read', 'write'] : wireTools ?? ['read', 'write', MAIL]);
  const receipts = structuredClone(task.reservation_receipts ?? []);
  const patterns = task.scope_mode === 'worktree' ? ['**'] : [...(task.allowed_paths ?? [])];
  let stopping = false;
  const guard = exec => {
    let reason, target, relative;
    try {
      if (stopping || !allowed.has(exec.name)) reason = 'not-in-wire-tools';
      else if (!exec.name.startsWith('mcp__orrery_mail__')) {
        target = canonicalTarget(root, exec.arguments?.file_path);
        if (!target) reason = 'outside-worktree';
        else {
          relative = path.relative(root, target);
          if (!patterns.some(p => matches(relative, p))) reason = 'not-reserved';
          else if (exec.name === 'write' || attempt.phase === 'spike') {
            const matching = receipts.filter(r => Number.isSafeInteger(r.id) && r.id > 0 &&
              r.owner === attempt.agent_name && matches(relative, r.relative_path ?? r.path_pattern));
            if (!matching.length) reason = 'not-reserved';
            else if (!matching.some(r => Number.isFinite(Date.parse(r.expires_ts)) && Date.parse(r.expires_ts) > now() + 1000))
              reason = 'reservation-expired';
          }
        }
      }
    } catch { reason = 'not-reserved'; }
    emit({phase: reason ? 'tool-denied' : 'tool-allowed', tool: exec.name,
      ...(relative !== undefined ? {path: relative} : {}), ...(reason ? {reason} : {})});
    return reason;
  };
  return {guard, stop: () => { stopping = true; }, root, allowed,
    addReceipt(relative, receipt) {
      if (receipt.owner !== attempt.agent_name || !Number.isSafeInteger(receipt.id) || receipt.id < 1)
        throw new Error('DSH_RESERVATION_IDENTITY');
      receipts.push({...receipt, relative_path: relative});
    },
    dropReceipt(id) { const i = receipts.findIndex(row => row.id === id); if (i >= 0) receipts.splice(i, 1); },
  };
}

export function createWriteReservationGate({attempt, task, policy, call, record}) {
  return async exec => {
    if (exec.name !== 'write' || attempt.phase !== 'run') return;
    const target = canonicalTarget(policy.root, exec.arguments?.file_path);
    if (!target) return; // The final monotonic guard owns path rejection.
    const relative = path.relative(policy.root, target);
    if (task.scope_mode !== 'worktree' && !(task.allowed_paths ?? []).some(p => matches(relative, p))) return;
    // Private-copy namespace only; never claim a lease on the live source file.
    const reserved = '_managed_workspaces/' + attempt.attempt_id + '/' + relative;
    const response = await call('reserve_files', {paths: [reserved], exclusive: true,
      ttl_seconds: 900, reason: 'Managed private-workspace edit'}, exec);
    const receipts = normalizeReservations(response, [reserved], attempt.agent_name);
    for (const row of receipts) {
      record(row, relative);
      policy.addReceipt(relative, row);
    }
    return receipts.map(row => row.id);
  };
}

export function mailReceipt(value) {
  if (value?.isError === true) return null;
  let receipt = value?.structuredContent;
  if (!receipt) {
    for (const block of value?.content ?? []) {
      if (block.type !== 'text') continue;
      try { receipt = JSON.parse(block.text); break; } catch { /* not JSON */ }
    }
  }
  const delivery = receipt?.deliveries?.[0]?.payload;
  if (!delivery) return null;
  return {message_id: delivery.id, to: Array.isArray(delivery.to) && delivery.to.length === 1 ? delivery.to[0] : delivery.to, from: delivery.from,
    verified_sender: receipt.verified_sender === true,
    ok: receipt.verified_sender === true && Number.isSafeInteger(delivery.id)};
}

export function installSessionEvents(ctx, emit, currentSession) {
  return ctx.on('session/event', (session, event) => {
    if (session.id !== currentSession()) return;
    if (event.type === 'turn/start') emit({phase: 'task-start', turn: event.data.turn});
    if (event.type === 'turn/end') emit({phase: 'turn-end', reason_kind: event.data.reason.kind, turn: event.data.turn});
  });
}

export function apply(ctx) {
  const state = process.env.ORRERY_DSH_STATE_ROOT;
  if (!state || !path.isAbsolute(state)) throw new Error('DSH_STATE_ROOT_REQUIRED');
  const attempt = JSON.parse(fs.readFileSync(path.join(state, 'attempt.json'), 'utf8'));
  const task = JSON.parse(fs.readFileSync(path.join(state, 'task.json'), 'utf8'));
  if (!['spike', 'run'].includes(attempt.phase) || !attempt.agent_name ||
      attempt.attempt_id !== task.attempt_id || attempt.attempt_id !== process.env.ORRERY_DSH_ATTEMPT_ID)
    throw new Error('DSH_MANIFEST_MISMATCH');
  if (attempt.phase === 'run' && task.reservation_source === 'offline-fixture')
    throw new Error('DSH_FIXTURE_RECEIPT_IN_RUN');
  let activeTaskId = task.task_id, reportedByMail = false;
  const emit = event => fs.appendFileSync(path.join(state, 'events.jsonl'), JSON.stringify({
    ...event, process_id: process.pid, attempt_id: attempt.attempt_id, task_id: activeTaskId, at: new Date().toISOString(),
  }) + '\n');
  const wireFile = path.join(state, 'wire-tools.json');
  const wire = fs.existsSync(wireFile) ? JSON.parse(fs.readFileSync(wireFile, 'utf8')) : null;
  if (wire && wire.attempt_id !== attempt.attempt_id) throw new Error('DSH_MAIL_SCHEMA_ATTEMPT');
  const policy = createReservationGuard({attempt, task, emit, wireTools: wire?.tools});
  ctx.tools.guard(policy.guard);
  const ledgerFile = path.join(state, 'reservation-ledger.json');
  const ledger = fs.existsSync(ledgerFile) ? JSON.parse(fs.readFileSync(ledgerFile, 'utf8')) :
    {attempt_id: attempt.attempt_id, agent_name: attempt.agent_name, receipts: [], released_ids: []};
  if (ledger.attempt_id !== attempt.attempt_id || ledger.agent_name !== attempt.agent_name)
    throw new Error('DSH_LEDGER_IDENTITY');
  const saveLedger = () => fs.writeFileSync(ledgerFile, JSON.stringify(ledger) + '\n', {mode: 0o600});
  const record = (receipt, relative) => {
    const old = ledger.receipts.find(row => row.id === receipt.id);
    const row = {...receipt, ...(relative !== undefined ? {relative_path: relative} : {})};
    if (old) Object.assign(old, row); else ledger.receipts.push(row);
    saveLedger();
  };
  let counter = 0;
  const call = async (name, args, exec) => {
    const result = await ctx.tools.execute({callId: 'orrery-reservation-' + ++counter,
      name: 'mcp__orrery_mail__' + name, arguments: args, agent: exec.agent, signal: exec.signal});
    if (result.isError) throw new Error('DSH_RESERVATION_RPC');
    return unwrap(result.value);
  };
  const gate = createWriteReservationGate({attempt, task, policy, call, record});
  const acquired = new Map();
  ctx.on('tools/pre-execute', async (exec, next) => {
    try {
      const ids = await gate(exec);
      if (ids) acquired.set(exec.callId, ids);
    } catch {
      emit({phase: 'tool-denied', tool: exec.name, reason: 'reservation-unavailable'});
      return {kind: 'deny', reason: 'reservation-unavailable'};
    }
    return next();
  });
  ctx.on('tools/execute', async (exec, next) => {
    try { return await next(); }
    finally {
      const ids = acquired.get(exec.callId);
      if (ids) {
        acquired.delete(exec.callId);
        try {
          const result = await call('release_reservations', {file_reservation_ids: ids}, exec);
          if (result.released !== ids.length) throw new Error('DSH_RELEASE_UNCONFIRMED');
          for (const id of ids) {
            if (!ledger.released_ids.includes(id)) ledger.released_ids.push(id);
            policy.dropReceipt(id);
          }
          saveLedger();
        } catch { emit({phase: 'reservation-release-pending'}); }
      }
    }
  });
  ctx.systemPrompt.section({name: 'orrery:worktree', order: 500,
    text: 'Use absolute file paths. This task may read and write only inside ' + policy.root + '.'});
  const verify = scope => {
    const adapter = [...ctx.get('loader').entries()].find(e => e.options.id === 'llm-deepseek');
    if (adapter?.options.config?.retryPolicy?.maxRetries !== 0) {
      policy.stop();
      throw new Error('DSH_RETRY_MUST_BE_ZERO');
    }
    // The runtime only permits restrict() on agent.ctx. Before the first
    // human prompt, verify registered allowed tools; the global monotonic
    // guard already denies the remaining unscoped tools.
    const names = ctx.tools.schemas(scope).map(t => t.name)
      .filter(name => scope !== undefined || policy.allowed.has(name)).sort();
    if (JSON.stringify(names) !== JSON.stringify([...policy.allowed].sort())) {
      policy.stop();
      emit({phase: 'tool-set-mismatch', tools: names});
      throw new Error('DSH_TOOL_SET_MISMATCH');
    }
    emit({phase: 'plugin-ready', tools: names, retry_count: 0});
  };
  let sessionId;
  // Blank native TUI sessions need readiness before the first human prompt.
  ctx.on('ready', () => verify(undefined));
  ctx.on('agent/created', async ({agent}) => {
    sessionId ??= agent.session.id;
    agent.ctx.tools.restrict({allow: [...policy.allowed]});
    verify(agent);
    if (attempt.phase === 'spike' && task.spike_probe === true) {
      const call = (id, file_path) => agent.ctx.tools.execute({
        callId: 'spike-' + id, name: 'write', agent,
        arguments: {file_path: path.resolve(policy.root, file_path), content: 'offline guard probe'},
        signal: new AbortController().signal,
      });
      const target = path.join(policy.root, 'probe/ok.txt');
      if (fs.existsSync(target)) await agent.ctx.tools.execute({
        callId: 'spike-read-before-write', name: 'read', agent,
        arguments: {file_path: target}, signal: new AbortController().signal,
      });
      const positive = await call('positive', 'probe/ok.txt');
      const denied = [];
      for (const [id, file] of [['outside', '../outside.txt'], ['missing', 'probe/unreserved.txt'], ['expired', 'probe/expired.txt']])
        denied.push((await call(id, file)).isError === true);
      const passed = positive.isError === false && denied.every(Boolean) &&
        fs.readFileSync(path.join(policy.root, 'probe/ok.txt'), 'utf8') === 'offline guard probe';
      emit({phase: 'spike-guard-probe', passed, positive_error: positive.isError,
        ...(positive.isError ? {positive_reason: positive.error.info?.code ?? positive.error.message} : {}), denied});
      if (!passed) { policy.stop(); throw new Error('DSH_SPIKE_GUARD_PROBE_FAILED'); }
    }
  });
  ctx.on('agent/pre-step', async ({agent}, next) => {
    verify(agent);
    return next();
  });
  ctx.on('tools/result', (exec, result) => {
    if (result.isError) return;
    if (exec.name === 'mcp__orrery_mail__reserve_files') {
      const response = unwrap(result.value);
      for (const row of response.granted ?? []) {
        if (Number.isSafeInteger(row.id) && row.id > 0)
          record({...row, owner: attempt.agent_name});
      }
    } else if (exec.name === 'mcp__orrery_mail__release_reservations') {
      const response = unwrap(result.value);
      const ids = exec.arguments?.file_reservation_ids ??
        ledger.receipts.map(row => row.id).filter(id => !ledger.released_ids.includes(id));
      if (Array.isArray(ids) && response.released === ids.length) {
        for (const id of ids) {
          if (!ledger.released_ids.includes(id)) ledger.released_ids.push(id);
          policy.dropReceipt(id);
        }
        saveLedger();
      }
    }
    if (exec.name === 'write') {
      const target = canonicalTarget(policy.root, exec.arguments?.file_path);
      if (target && fs.statSync(target).isFile())
        emit({phase: 'artifact-written', path: path.relative(policy.root, target), sha256: digest(target)});
    } else if (exec.name === MAIL) {
      const receipt = mailReceipt(result.value);
      if (receipt) {
        emit({phase: 'mail-sent', ...receipt});
        if (receipt.ok && receipt.from === attempt.agent_name && receipt.to === task.report_to)
          reportedByMail = true;
      }
    }
  });
  const expectedReady = () => (task.expected ?? []).every(spec => {
    try {
    const file = canonicalTarget(policy.root, path.resolve(policy.root, spec.path));
    if (!file || !fs.statSync(file).isFile()) return false;
    const data = fs.readFileSync(file);
    return spec.sha256 ? createHash('sha256').update(data).digest('hex') === spec.sha256 :
      typeof spec.contains === 'string' && data.includes(Buffer.from(spec.contains));
    } catch { return false; }
  });
  installSessionEvents(ctx, event => {
    emit(event);
    if (activeTaskId && task.task_mode === 'assignment' && event.phase === 'turn-end' &&
        event.reason_kind === 'completed' &&
        (task.report_policy === 'mail' ? reportedByMail : expectedReady())) {
      emit({phase: 'task-report-finalized'});
      activeTaskId = null;
    }
  }, () => sessionId);
  ctx.on('dispose', () => policy.stop());
}
