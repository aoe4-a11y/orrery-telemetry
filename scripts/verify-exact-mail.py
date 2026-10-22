#!/usr/bin/env python3
"""Prove exact retrieval over isolated HTTP with a copied synthetic database.

Never opens a production database, credential file, or service controller.
Pass a fresh scratch directory and a durable JSON output path.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time

from agentstack_codex_app.agent_mail_client import AgentMailClient, HttpJsonRpcTransport


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scratch', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    root = args.scratch.resolve()
    root.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ('AGENTSTACK_', 'CODEX_', 'CLAUDE_')) and k not in {
        'AGENT_NAME', 'PARENT_AGENT', 'PROJECT_KEY', 'CHILD_REGISTRATION_TOKEN',
        'MCP_AGENT_MAIL_TOKEN', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'}}
    home = root / 'home'
    home.mkdir()
    seed, copy = root / 'seed.sqlite3', root / 'copy.sqlite3'
    # Initialize the real model schema in a clean subprocess, then snapshot
    # only this synthetic seed. No existing database is accepted as an input.
    env.update(HOME=str(home), AGENTSTACK_MAIL_ENV_FILE=str(root / 'absent.env'),
               AGENTSTACK_MAIL_DATABASE_URL='sqlite+aiosqlite:///' + str(seed),
               AGENTSTACK_MAIL_STORAGE_ROOT=str(root / 'archive'),
               AGENTSTACK_MAIL_NOTIFICATIONS_SIGNALS_DIR=str(root / 'signals'),
               AGENTSTACK_MAIL_AGENT_NAME_ENFORCEMENT_MODE='passthrough',
               AGENTSTACK_MAIL_MANAGEMENT_SOCKET='',
               AGENTSTACK_MAIL_NOTIFICATIONS_ENABLED='false')
    subprocess.run([sys.executable, '-c',
                    'import asyncio; import agentstack_mail.models; '
                    'from agentstack_mail.db import ensure_schema, get_engine; '
                    'async def seed():\n await ensure_schema()\n await get_engine().dispose()\n'
                    'asyncio.run(seed())'.replace('; async def', '\nasync def')],
                   env=env, check=True)
    seed_sha = hashlib.sha256(seed.read_bytes()).hexdigest()
    with sqlite3.connect(seed) as src, sqlite3.connect(copy) as dst:
        src.backup(dst)
    copy_sha = hashlib.sha256(copy.read_bytes()).hexdigest()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    assert port != 18765
    env['AGENTSTACK_MAIL_DATABASE_URL'] = 'sqlite+aiosqlite:///' + str(copy)
    env['AGENTSTACK_MAIL_HTTP_PORT'] = str(port)
    endpoint = f'http://127.0.0.1:{port}/mcp'
    evidence = {'endpoint': endpoint, 'seed_db': str(seed), 'copied_db': str(copy),
                'seed_sha256': seed_sha, 'copy_before_sha256': copy_sha,
                'production_db_opened': False}
    with (root / 'server.log').open('wb') as log:
        process = subprocess.Popen([str(Path(sys.executable).parent / 'agentstack-mail'),
                                    '--host', '127.0.0.1', '--port', str(port)],
                                   env=env, stdout=log, stderr=subprocess.STDOUT)
        def watcher():
            process.wait()
            (root / 'server.done').write_text(str(process.returncode) + '\n')
        thread = threading.Thread(target=watcher)
        thread.start()
        try:
            transport = HttpJsonRpcTransport(endpoint, timeout=2)
            deadline = time.monotonic() + 45
            while True:
                try:
                    response = transport({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
                    tools = response['result']['tools']
                    break
                except Exception:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise
                    time.sleep(.2)
            schema = next(t for t in tools if t['name'] == 'fetch_inbox')['inputSchema']
            assert 'message_id' in schema['properties']
            evidence['message_id_schema'] = schema['properties']['message_id']
            client = AgentMailClient(transport)
            project = str(root / 'synthetic-project')
            client._call_tool('ensure_project', {'human_key': project})
            # Public synthetic fixture values, unrelated to any live identity.
            for name in ('ExactSender', 'ExactRecipient', 'ExactOutsider'):
                client.register_agent(project_key=project, model='offline-fixture',
                                      agent_name=name, registration_token='fixture-' + name)
            body = 'ORRERY-UP-3 synthetic exact body\n' * 500
            sent = client.send_message(project_key=project, agent_name='ExactSender',
                                       registration_token='fixture-ExactSender',
                                       to=['ExactRecipient'], subject='[station] exact fixture', body_md=body)
            # Avoid depending on compact-send envelope details: the database
            # here is OUR disposable copy, never the live database.
            with sqlite3.connect(copy) as db:
                message_id, = db.execute('SELECT id FROM messages').fetchone()
                db.execute("UPDATE messages SET created_ts='2001-01-01 00:00:00'")
            rows = client.fetch_inbox(project_key=project, agent_name='ExactRecipient',
                                      registration_token='fixture-ExactRecipient',
                                      message_id=message_id, include_bodies=True)
            assert len(rows) == 1 and rows[0]['id'] == message_id
            assert rows[0]['body_md'] == body
            outsiders = client.fetch_inbox(project_key=project, agent_name='ExactOutsider',
                                          registration_token='fixture-ExactOutsider',
                                          message_id=message_id, include_bodies=True)
            assert outsiders == []
            recent = client.fetch_inbox(project_key=project, agent_name='ExactRecipient',
                                       registration_token='fixture-ExactRecipient',
                                       since_ts='2026-01-01T00:00:00Z', include_bodies=True)
            assert recent == []
            assert hashlib.sha256(seed.read_bytes()).hexdigest() == seed_sha
            evidence.update(message_id=message_id, sent_count=1, received_count=len(rows),
                            body_chars=len(body), body_sha256=hashlib.sha256(body.encode()).hexdigest(),
                            body_equal=True, old_message_exact=True, nonrecipient_count=0,
                            recent_filter_count=0, seed_unchanged=True, status='passed')
        finally:
            process.terminate()
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            thread.join(timeout=1)
            with socket.socket() as probe:
                evidence['port_closed'] = probe.connect_ex(('127.0.0.1', port)) != 0
            evidence['server_exit'] = process.returncode
            args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    assert evidence['port_closed']
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
