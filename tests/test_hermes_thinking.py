"""Pinned native transport/SDK wire proof with a synthetic loopback provider."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

WIRE_SCRIPT = r'''
import importlib.util,json,os,shutil,socket,subprocess,sys,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
real_socket,real_popen=socket.socket,subprocess.Popen
sys.path.insert(0,str(Path(os.environ['FIXTURE_PRODUCT'])/'tests'))
from test_hermes_thin_config import ThinConfig,config
fixture=ThinConfig();fixture.setUp()
server=worker=None
clients=[];records=[]
try:
    native=Path(os.environ['ORRERY_HERMES_TEST_SOURCE'])
    for name in ('auth.py','config_defaults.py'):
        shutil.copyfile(native/'hermes_cli'/name,fixture.source/'hermes_cli'/name)
    fixture.profile_spec.update(model='deepseek-flash',base_url='https://api.deepseek.com/anthropic',api_mode='anthropic_messages')
    fixture.manifest_data['backends']['deepseek']={'model':'deepseek-flash'}
    fixture.save(fixture.template,fixture.template_data);fixture.save(fixture.manifest,fixture.manifest_data)
    fixture.document['model']='deepseek-flash'
    plan=fixture.generate()
    assert '--reasoning' not in plan['argv']
    overlay=config.read(Path(plan['config_dir'])/'config.yaml')
    provider=plan['argv'][3];route=overlay['providers'][provider]
    assert route['api_mode']=='chat_completions' and route['base_url']=='https://api.deepseek.com/v1'
    socket.socket,subprocess.Popen=real_socket,real_popen
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assistants=[m for m in body['messages'] if m['role']=='assistant']
            anthropic=self.path.endswith('/messages')
            replay=not assistants or (any(b.get('type')=='thinking' for b in assistants[-1]['content'])
                                     if anthropic else assistants[-1].get('reasoning_content')=='fixture-thought')
            records.append({'protocol':'anthropic' if anthropic else 'chat','replayed':bool(assistants and replay)})
            if assistants and not replay:
                result={'error':{'type':'invalid_request_error','message':'fixture requires thinking pass-back'}};status=400
            elif anthropic:
                result={'id':'msg_fixture','type':'message','role':'assistant','model':body['model'],
                    'content':[{'type':'thinking','thinking':'fixture-thought','signature':'00000000-0000-0000-0000-000000000000'},
                               {'type':'tool_use','id':'call_fixture','name':'fixture_tool','input':{}}],
                    'stop_reason':'tool_use','stop_sequence':None,'usage':{'input_tokens':1,'output_tokens':1}};status=200
            else:
                message=({'role':'assistant','content':'fixture-complete'} if assistants else
                    {'role':'assistant','content':None,'reasoning_content':'fixture-thought',
                     'tool_calls':[{'id':'call_fixture','type':'function','function':{'name':'fixture_tool','arguments':'{}'}}]})
                result={'id':'chatcmpl_fixture','object':'chat.completion','created':0,'model':body['model'],
                    'choices':[{'index':0,'message':message,'finish_reason':'stop' if assistants else 'tool_calls'}],
                    'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}};status=200
            data=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    def audit(event,args):
        if event=='socket.connect' and args[1]!=('127.0.0.1',server.server_port):
            raise AssertionError('external network forbidden')
        if event=='socket.getaddrinfo' and args[0]!='127.0.0.1':
            raise AssertionError('external DNS forbidden')
        if event=='subprocess.Popen':
            argv=args[1]
            if Path(argv[0]).name=='git' and any(p in argv for p in ('rev-parse','describe','log','status','show','rev-list','branch','tag')):
                return  # read-only provenance for the legacy unstamped fixture source
            raise AssertionError('credential helper and other children forbidden')
    sys.addaudithook(audit)
    os.environ.update(plan['env']);sys.path.insert(0,str(native))
    from hermes_cli.config import load_config
    from hermes_cli.runtime_provider import resolve_runtime_provider
    load_config()
    runtime=resolve_runtime_provider(requested=provider,target_model='deepseek-flash')
    assert runtime['api_mode']=='chat_completions' and runtime['base_url']==route['base_url']
    from agent.transports.anthropic import AnthropicTransport
    from agent.transports.chat_completions import ChatCompletionsTransport
    import anthropic,openai
    tools=[{'type':'function','function':{'name':'fixture_tool','description':'fixture','parameters':{'type':'object','properties':{}}}}]
    origin=f'http://127.0.0.1:{server.server_port}'
    for old in (True,False):
        transport=AnthropicTransport() if old else ChatCompletionsTransport()
        client=(anthropic.Anthropic if old else openai.OpenAI)(api_key='fixture-local-token',base_url=origin+'/v1',max_retries=0,timeout=5)
        clients.append(client)
        history=[{'role':'user','content':'fixture tool'}]
        params={'reasoning_config':None,'base_url':'https://api.deepseek.com/anthropic' if old else route['base_url']}
        if old: params['max_tokens']=4096
        else: params['provider_name']=runtime['provider']
        send=client.messages.create if old else client.chat.completions.create
        first=send(**transport.build_kwargs('deepseek-flash',history,tools,**params))
        normalized=transport.normalize_response(first)
        history.append({'role':'assistant','content':normalized.content,
            'tool_calls':[{'id':t.id,'type':'function','function':{'name':t.name,'arguments':t.arguments}} for t in normalized.tool_calls],
            **(normalized.provider_data or {})})
        history.append({'role':'tool','tool_call_id':'call_fixture','content':'fixture result'})
        second=transport.build_kwargs('deepseek-flash',history,tools,**params)
        if old:
            try: send(**second)
            except anthropic.BadRequestError: pass
            else: raise AssertionError('old signed-strip regression not reproduced')
        else:
            response=send(**second)
            assert response.choices[0].message.content=='fixture-complete'
    assert records==[{'protocol':'anthropic','replayed':False},{'protocol':'anthropic','replayed':False},
                     {'protocol':'chat','replayed':False},{'protocol':'chat','replayed':True}],records
    print(json.dumps({'success':True,'local_requests':len(records),'effort':None,'records':records,'external_requests':0}))
finally:
    for client in clients: client.close()
    if server is not None: server.shutdown();server.server_close()
    if worker is not None: worker.join(timeout=5)
    fixture.doCleanups()
'''


class NativeThinking(unittest.TestCase):
    def test_unspecified_effort_replays_thinking_on_second_sdk_wire_request(self):
        source, python = os.environ.get('ORRERY_HERMES_TEST_SOURCE'), os.environ.get('ORRERY_HERMES_TEST_PYTHON')
        if not source or not python:
            self.skipTest('Explicit installed dependency interpreter/source required')
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run([python, '-I', '-B', '-c', WIRE_SCRIPT], cwd='/',
                env={'HOME':home,'PATH':os.defpath,'PYTHONDONTWRITEBYTECODE':'1',
                     'HERMES_DISABLE_LAZY_INSTALLS':'1','UV_OFFLINE':'1',
                     'FIXTURE_PRODUCT':str(ROOT),'ORRERY_HERMES_TEST_SOURCE':source},
                capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"success": true', result.stdout)


if __name__ == '__main__':
    unittest.main()
