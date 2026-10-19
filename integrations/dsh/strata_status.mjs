// Shared-server busy/auth/timeout states are observations, never admission gates.
export async function observeStatus(fetchImpl, baseURL, key, audit, timeoutMs = 5000, callers = () => []) {
  try {
    for (const endpoint of ['/v1/status', '/health']) {
      const url = new URL(endpoint, baseURL);
      let response = await fetchImpl(url, {redirect: 'manual', signal: AbortSignal.timeout(timeoutMs)});
      if (response.status === 401 || response.status === 403) {
        if (!key) throw new Error('STATUS_AUTH_REQUIRED');
        response = await fetchImpl(url, {redirect: 'manual',
          headers: {Authorization: 'Bearer ' + key}, signal: AbortSignal.timeout(timeoutMs)});
      }
      if (response.status >= 300 && response.status < 400) {
        audit({phase: 'status-check', busy: null, reason: 'STATUS_REDIRECT', from_origin: url.origin,
          method: 'GET', host: url.hostname, port: Number(url.port || (url.protocol === 'https:' ? 443 : 80)),
          path: url.pathname, callers: callers()});
        return null;
      }
      if (response.status === 404) continue;
      if (!response.ok) throw new Error('STATUS_UNAVAILABLE');
      const value = await response.json();
      const n = value.activity?.in_flight ?? value.in_flight;
      const q = value.activity?.queued ?? value.activity?.queue ?? value.queued ?? value.queue;
      const known = typeof n === 'number' && (q === undefined || typeof q === 'number');
      const busy = known ? n !== 0 || (q !== undefined && q !== 0) : null;
      audit({phase: 'status-check', busy});
      return busy;
    }
    throw new Error('STATUS_MISSING');
  } catch {
    audit({phase: 'status-check', busy: null, reason: 'STATUS_UNAVAILABLE'});
    return null;
  }
}
