#!/usr/bin/env python3
"""Run one job with a completion watcher and an unfiltered, durable log."""
import argparse,os,pathlib,subprocess,sys,threading,time
ap=argparse.ArgumentParser();ap.add_argument('--log',type=pathlib.Path,required=True);ap.add_argument('command',nargs=argparse.REMAINDER);a=ap.parse_args();cmd=a.command
if cmd[:1]==['--']:cmd=cmd[1:]
a.log.parent.mkdir(parents=True,exist_ok=True)
with a.log.open('wb') as log:
 p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 def watcher():
  while p.poll() is None:time.sleep(.25)
  a.log.with_suffix(a.log.suffix+'.done').write_text(str(p.returncode)+'\n')
  print('WATCHER: job ended, exit='+str(p.returncode),flush=True)
 t=threading.Thread(target=watcher);t.start()
 for chunk in iter(lambda:p.stdout.read1(4096),b''):
  log.write(chunk);log.flush();sys.stdout.buffer.write(chunk);sys.stdout.buffer.flush()
 result=p.wait();t.join();log.write(('\nEXIT_CODE='+str(result)+'\n').encode())
sys.exit(result)
