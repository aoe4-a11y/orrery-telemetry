"""Raw usage evidence with real HTTPX, offline streams, and no credential lookup."""
import asyncio
from contextvars import ContextVar
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ADAPTER = Path(__file__).resolve().parents[1] / 'integrations/hermes'
sys.path.insert(0, str(ADAPTER))
from usage_guard import Usage, wrap_response


def event(value):
    return ('data: ' + json.dumps(value) + '\n\n').encode()

START = event({'type': 'message_start', 'message': {'usage': {'input_tokens': 11, 'output_tokens': 0}}})
DELTA = event({'type': 'message_delta', 'usage': {'output_tokens': 3}})
STOP = event({'type': 'message_stop'})
PERMITTED = ContextVar('usage_fixture_permitted', default=False)


class UsageTests(unittest.TestCase):
    def test_split_sse_preserves_real_zero_and_requires_final_usage(self):
        rows = []
        usage = Usage('anthropic_messages', 'text/event-stream', rows.append)
        payload = START + DELTA + STOP
        for offset in range(0, len(payload), 7):
            usage.feed(payload[offset:offset + 7])
        usage.eof()
        self.assertTrue(usage.close())
        self.assertEqual(rows[0]['usage']['input'], 11)
        for payload in (START + STOP, START + event({'type': 'message_delta', 'usage': None}) + STOP,
                        START + DELTA, event({'type': 'message_start', 'message': {'usage': None}}) + DELTA + STOP):
            usage = Usage('anthropic_messages', 'text/event-stream', lambda row: None)
            usage.feed(payload); usage.eof()
            self.assertFalse(usage.close())
        usage = Usage('anthropic_messages', 'text/event-stream', lambda row: None)
        usage.feed(START + event({'type': 'message_delta', 'usage': {'output_tokens': 0}}) + STOP)
        self.assertTrue(usage.close())

    def test_interrupt_and_close_failure_never_confirm(self):
        for payload, ok in ((START + DELTA, True), (START + DELTA + STOP, False)):
            rows = []
            usage = Usage('anthropic_messages', 'text/event-stream', rows.append)
            usage.feed(payload)
            self.assertFalse(usage.close(ok))
            self.assertFalse(rows[-1]['confirmed'])

    def test_json_and_openai_stream_need_raw_counts_and_terminal(self):
        for mode, body in (('anthropic_messages', {'usage': {'input_tokens': 2, 'output_tokens': 0}}),
                           ('chat_completions', {'usage': {'prompt_tokens': 2, 'completion_tokens': 4}})):
            usage = Usage(mode, 'application/json', lambda row: None)
            usage.feed(json.dumps(body).encode()); usage.eof()
            self.assertTrue(usage.close())
        for ending, good in ((b'data: [DONE]\n\n', True), (b'', False)):
            usage = Usage('chat_completions', 'text/event-stream', lambda row: None)
            usage.feed(event({'usage': {'prompt_tokens': 2, 'completion_tokens': 4}}) + ending)
            usage.eof()
            self.assertEqual(usage.close(), good)

    def test_real_httpx_decodes_gzip_before_observing_and_preserves_bytes(self):
        import httpx
        for content_type, payload in (('text/event-stream', START + DELTA + STOP),
                                      ('application/json', b'{"usage":{"input_tokens":11,"output_tokens":3}}')):
            compressed = gzip.compress(payload)
            class Stream(httpx.SyncByteStream):
                def __iter__(self):
                    for at in range(0, len(compressed), 9):
                        yield compressed[at:at + 9]
            with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200,
                    headers={'content-type': content_type, 'content-encoding': 'gzip'}, stream=Stream()))) as client:
                response = client.send(client.build_request('POST', 'https://fixture.invalid/v1/messages'), stream=True)
                rows = []
                wrap_response(response, 'anthropic_messages', rows.append, PERMITTED)
                self.assertEqual(response.read(), payload)
                self.assertTrue(rows[-1]['confirmed'])
                self.assertFalse(PERMITTED.get())

    def test_real_httpx_cancel_after_terminal_is_valid_but_close_exception_is_not(self):
        import httpx
        for terminal, broken in ((True, False), (False, False), (True, True)):
            class Stream(httpx.SyncByteStream):
                def __iter__(self):
                    yield START + DELTA + (STOP if terminal else b'')
                    raise httpx.ReadTimeout('PRIVATE')
                def close(self):
                    if broken:
                        raise httpx.ReadError('PRIVATE')
            response = httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream())
            rows = []
            wrap_response(response, 'anthropic_messages', rows.append, PERMITTED)
            iterator = response.iter_bytes()
            next(iterator)
            iterator.close()
            if broken:
                with self.assertRaises(httpx.ReadError):
                    response.close()
            else:
                response.close()
            self.assertEqual(rows[-1]['confirmed'], terminal and not broken)
            self.assertNotIn('PRIVATE', json.dumps(rows))

    def test_real_httpx_timeout_after_terminal_does_not_become_success(self):
        import httpx
        class Stream(httpx.SyncByteStream):
            def __iter__(self):
                yield START + DELTA + STOP
                raise httpx.ReadTimeout('PRIVATE')
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream())
        rows = []
        wrap_response(response, 'anthropic_messages', rows.append, PERMITTED)
        with self.assertRaises(httpx.ReadTimeout):
            response.read()
        response.close()
        self.assertFalse(rows[-1]['confirmed'])
        self.assertFalse(PERMITTED.get())

    def test_real_async_httpx_stream_and_early_cancel(self):
        import httpx
        async def check(terminal, broken):
            class Stream(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield START + DELTA + (STOP if terminal else b'')
                async def aclose(self):
                    if broken:
                        raise httpx.ReadError('PRIVATE')
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,
                    headers={'content-type': 'text/event-stream'}, stream=Stream()))) as client:
                response = await client.send(client.build_request('POST', 'https://fixture.invalid/v1/messages'), stream=True)
                rows = []
                wrap_response(response, 'anthropic_messages', rows.append, PERMITTED)
                iterator = response.aiter_bytes()
                await iterator.__anext__()
                await iterator.aclose()
                if broken:
                    with self.assertRaises(httpx.ReadError):
                        await response.aclose()
                else:
                    await response.aclose()
                self.assertEqual(rows[-1]['confirmed'], terminal and not broken)
                self.assertFalse(PERMITTED.get())
        for terminal, broken in ((True, False), (False, False), (True, True)):
            asyncio.run(check(terminal, broken))

    def test_installed_transport_guard_blocks_next_request_after_missing_usage(self):
        # install() adds an irreversible audit hook: isolate the complete real
        # HTTPX install path in a child, rather than affecting unrelated tests.
        code = r'''
import httpx,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from provider_audit import install
root=Path(sys.argv[2]); source=root/'source';source.mkdir()
(root/'attempt.json').write_text(json.dumps({'attempt_id':'fixture'}))
(root/'activity.json').write_text(json.dumps({'task_id':'task-1','turn_id':'turn-1'}))
(root/'profile').mkdir()
(root/'profile/config.yaml').write_text(json.dumps({'providers':{'fixture':{'base_url':'https://fixture.invalid','api_mode':'anthropic_messages'}}}))
(root/'run-config.json').write_text(json.dumps({'profile_home':str(root/'profile'),'provider':'fixture','hermes_source':str(source)}))
policy=install(root)
start=b'data: {"type":"message_start","message":{"usage":{"input_tokens":5,"output_tokens":0}}}\n\n'
delta=b'data: {"type":"message_delta","usage":{"output_tokens":1}}\n\n'
stop=b'data: {"type":"message_stop"}\n\n'
calls=[]
class Stream(httpx.SyncByteStream):
 def __iter__(self):
  yield start+(delta if len(calls)==1 else b'')+stop
def transport(request):
 calls.append(1)
 return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
with httpx.Client(transport=httpx.MockTransport(transport)) as client:
 client.post('https://fixture.invalid/v1/messages').read()
 (root/'activity.json').write_text(json.dumps({'task_id':'task-2','turn_id':'turn-2'}))
 client.post('https://fixture.invalid/v1/messages').read()
 try:client.post('https://fixture.invalid/v1/messages')
 except RuntimeError:pass
 else:raise AssertionError('missing raw usage allowed next request')
assert len(calls)==2
rows=[json.loads(line) for line in (root/'audit.jsonl').read_text().splitlines()]
u=[r for r in rows if r['phase']=='provider-usage']
assert [r['confirmed'] for r in u]==[True,False],u
assert u[0]['turn_id']=='turn-1' and u[1]['turn_id']=='turn-2'
assert not policy.usage_known
print('real HTTPX install: two forwards; third blocked; binding preserved')
'''
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, '-c', code, str(ADAPTER), tmp], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('third blocked', result.stdout)


if __name__ == '__main__':
    unittest.main()
