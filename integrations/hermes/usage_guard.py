"""Observe original decoded provider bytes before SDK usage normalization.

A missing usage field is common on interrupted streams; accepting it can falsely
report success. Keep only counts and protocol state in audit, never the payload.
"""
import codecs
import json


def count(value):
    return type(value) is int and value >= 0


class Usage:
    def __init__(self, mode, content_type, emit):
        self.mode = mode
        self.sse = 'text/event-stream' in content_type
        self.emit = emit
        self.decoder = codecs.getincrementaldecoder('utf-8')()
        self.pending, self.data = '', []
        self.input = self.output = None
        self.cache = None
        self.final = self.terminal = self.failed = self.ended = False
        self.reported = None

    def feed(self, chunk):
        text = self.decoder.decode(chunk)
        self.pending += text
        if not self.sse:
            return
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            line = line.rstrip('\r')
            if not line:
                self.frame()
            elif line.startswith('data:'):
                self.data.append(line[5:].lstrip(' '))

    def frame(self):
        if not self.data:
            return
        data, self.data = '\n'.join(self.data), []
        if data == '[DONE]' and self.mode != 'anthropic_messages':
            self.terminal = True
            return
        try:
            event = json.loads(data)
        except (ValueError, TypeError):
            return
        if not isinstance(event, dict):
            return
        if self.mode == 'anthropic_messages':
            kind = event.get('type')
            if kind == 'message_start':
                message = event.get('message')
                self.observe(message.get('usage') if isinstance(message, dict) else None, final=False)
            elif kind == 'message_delta':
                self.observe(event.get('usage'), final=True)
            elif kind == 'message_stop':
                self.terminal = True
            elif kind == 'error':
                self.failed = True
        else:
            if 'usage' in event and event['usage'] is not None:
                self.observe(event['usage'], final=True)
            if event.get('error'):
                self.failed = True

    def observe(self, usage, final):
        if not isinstance(usage, dict):
            if final:
                self.final = False
            return
        ik, ok = ('input_tokens', 'output_tokens') if self.mode == 'anthropic_messages' else ('prompt_tokens', 'completion_tokens')
        if ik in usage:
            self.input = usage[ik] if count(usage[ik]) else None
        if ok in usage:
            self.output = usage[ok] if count(usage[ok]) else None
        if 'cache_read_input_tokens' in usage:
            self.cache = usage['cache_read_input_tokens'] if count(usage['cache_read_input_tokens']) else None
        if final:
            self.final = count(usage.get(ok))

    def eof(self):
        self.pending += self.decoder.decode(b'', final=True)
        if self.sse:
            if self.pending.startswith('data:'):
                self.data.append(self.pending[5:].lstrip(' '))
            self.pending = ''
            self.frame()
        else:
            try:
                result = json.loads(self.pending)
                self.observe(result.get('usage'), final=True)
                self.terminal = not result.get('error')
            except (ValueError, TypeError, AttributeError):
                self.failed = True
            self.pending = ''
        self.ended = True

    def close(self, ok=True):
        self.failed = self.failed or not ok
        confirmed = bool(not self.failed and self.final and self.terminal and count(self.input) and count(self.output))
        # An error following an earlier close is an explicit correction, never a
        # second positive receipt. Consumers use the last row for the sequence.
        if confirmed != self.reported:
            self.reported = confirmed
            self.emit({'confirmed': confirmed, 'terminal': self.terminal,
                       'usage': {'input': self.input, 'output': self.output, 'cache_read': self.cache}})
        return confirmed


def wrap_response(response, mode, emit, permitted):
    """Tap HTTPX transport bytes using its own content decoder; preserve SDK bytes."""
    import httpx
    usage = Usage(mode, response.headers.get('content-type', ''), emit)
    # HTTPX caches the decoder on each Response. Use a separate instance so
    # observation cannot consume the SDK's decompression state.
    decoder = httpx.Response(200, headers=response.headers)._get_content_decoder()
    original = response.stream

    class Sync(httpx.SyncByteStream):
        def __iter__(self):
            iterator = iter(original)
            try:
                while True:
                    token = permitted.set(True)
                    try:
                        chunk = next(iterator)
                    except StopIteration:
                        break
                    finally:
                        permitted.reset(token)
                    usage.feed(decoder.decode(chunk))
                    yield chunk
                usage.feed(decoder.flush())
                usage.eof()
            except GeneratorExit:
                raise
            except BaseException:
                usage.close(False)
                raise

        def close(self):
            try:
                original.close()
            except BaseException:
                usage.close(False)
                raise
            usage.close()

    class Async(httpx.AsyncByteStream):
        async def __aiter__(self):
            iterator = original.__aiter__()
            try:
                while True:
                    token = permitted.set(True)
                    try:
                        chunk = await iterator.__anext__()
                    except StopAsyncIteration:
                        break
                    finally:
                        permitted.reset(token)
                    usage.feed(decoder.decode(chunk))
                    yield chunk
                usage.feed(decoder.flush())
                usage.eof()
            except GeneratorExit:
                raise
            except BaseException:
                usage.close(False)
                raise

        async def aclose(self):
            try:
                await original.aclose()
            except BaseException:
                usage.close(False)
                raise
            usage.close()

    response.stream = Async() if isinstance(original, httpx.AsyncByteStream) else Sync()
    # A custom transport may return an already-buffered response, whose iterator
    # bypasses stream entirely. Those original decoded bytes remain evidence.
    if response.is_stream_consumed:
        usage.feed(response.content)
        usage.eof()
        usage.close()
    return usage
