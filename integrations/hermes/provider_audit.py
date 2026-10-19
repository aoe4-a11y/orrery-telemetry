"""Synchronous HTTPX policy for the pinned Hermes OpenAI/Anthropic routes.

No request headers, bodies, credential values or remote error strings are saved.
This is a Python transport boundary, not an operating-system process sandbox.
"""
from contextvars import ContextVar
import json
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit

from mail_lifecycle import read
from task_evidence import audit, callers
from usage_guard import wrap_response

_permitted = ContextVar('orrery_http_transport', default=False)


class Policy:
    def __init__(self, state, limit=None):
        self.state = Path(state)
        config = read(self.state / 'run-config.json')
        limit = config.get('provider_request_limit') if limit is None else limit
        if (limit is not None or 'provider_request_limit' in config) and (type(limit) is not int or limit < 1):
            raise ValueError('Provider request limit must be a positive integer when specified')
        profile = read(Path(config.get('runtime_config') or Path(config['profile_home']) / 'config.yaml'))
        route = profile['providers'][config['provider']]
        self.api_mode = route['api_mode']
        base = urlsplit(route['base_url'])
        path = base.path.rstrip('/')
        # Hermes strips trailing /v1 for Anthropic; the SDK appends /v1/messages.
        path = path.removesuffix('/v1') + '/v1/messages' if route['api_mode'] == 'anthropic_messages' else path + '/chat/completions'
        self.endpoint = (base.scheme, base.netloc, path)
        self.limit, self.seq, self.lock = limit, 0, threading.Lock()
        self.active = None
        self.usage_known = True
        self.bindings = {}

    def before(self, request):
        url = urlsplit(str(request.url))
        if (request.method != 'POST' or (url.scheme, url.netloc, url.path) != self.endpoint
                or url.query or url.fragment):
            audit(self.state, 'blocked-network', reason='endpoint-not-allowed', method=request.method,
                  host=url.hostname, port=url.port or (443 if url.scheme == 'https' else 80),
                  path=url.path, callers=callers(self.state))
            raise RuntimeError('Managed provider endpoint denied')
        with self.lock:
            if self.active is not None or not self.usage_known:
                audit(self.state, 'limit-reached', reason='usage-unknown' if not self.usage_known else 'request-in-flight')
                raise RuntimeError('Managed provider usage is unconfirmed')
            if self.limit is not None and self.seq >= self.limit:
                audit(self.state, 'limit-reached', limit=self.limit)
                raise RuntimeError('Managed provider request limit reached')
            self.seq += 1
            seq = self.seq
            self.active = seq
            self.usage_known = False
            active = read(self.state / 'activity.json') if (self.state / 'activity.json').is_file() else {}
            self.bindings[seq] = {'task_id': active.get('task_id'), 'turn_id': active.get('turn_id')}
        audit(self.state, 'provider-request-start', seq=seq, **self.bindings[seq])
        return seq

    def usage(self, seq, row):
        audit(self.state, 'provider-usage', seq=seq, **self.bindings[seq], **row)
        with self.lock:
            if self.active == seq:
                self.active = None
            self.usage_known = row['confirmed'] is True

    def failed(self, seq):
        self.usage(seq, {'confirmed': False, 'terminal': False, 'usage': None})

    def response(self, seq, status):
        audit(self.state, 'provider-response', seq=seq, status=status)


def install(state):
    import httpx
    policy = Policy(state)
    original_sync = httpx.Client._send_single_request
    original_async = httpx.AsyncClient._send_single_request

    def send(client, request):
        seq = policy.before(request)
        token = _permitted.set(True)
        try:
            result = original_sync(client, request)
            policy.response(seq, result.status_code)
            if not result.is_success:
                policy.failed(seq)
            else:
                wrap_response(result, policy.api_mode, lambda row: policy.usage(seq, row), _permitted)
            return result
        except BaseException:
            policy.failed(seq)
            raise
        finally:
            _permitted.reset(token)

    async def asend(client, request):
        seq = policy.before(request)
        token = _permitted.set(True)
        try:
            result = await original_async(client, request)
            policy.response(seq, result.status_code)
            if not result.is_success:
                policy.failed(seq)
            else:
                wrap_response(result, policy.api_mode, lambda row: policy.usage(seq, row), _permitted)
            return result
        except BaseException:
            policy.failed(seq)
            raise
        finally:
            _permitted.reset(token)

    httpx.Client._send_single_request = send
    httpx.AsyncClient._send_single_request = asend

    def guard(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo') and not _permitted.get():
            address = args[1] if event == 'socket.connect' else args
            host = address[0] if isinstance(address, tuple) and address else None
            port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
            audit(state, 'blocked-network', reason='outside-httpx-provider-transport',
                  method=None, host=host, port=port, path=None, callers=callers(state))
            raise RuntimeError('Unmanaged Python network operation denied')
    sys.addaudithook(guard)
    audit(state, 'preload-ready', backend_id=read(Path(state) / 'run-config.json')['provider'])
    return policy
