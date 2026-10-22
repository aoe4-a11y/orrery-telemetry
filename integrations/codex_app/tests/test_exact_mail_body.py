"""Recipient-scoped exact retrieval and lossless chunk recovery through the proxy."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import SQLModel, Session

from agentstack_mail import app
from agentstack_mail.models import Agent, Message, MessageRecipient, Project
from agentstack_codex_app.agent_mail_client import AgentMailClient, AgentMailError
from agentstack_codex_app.identity_store import IdentityStore, build_binding
from agentstack_codex_app.mcp_server import AgentStackProxy, StdioMcpServer, ProxyError
from agentstack_codex_app.snapshot import SnapshotStore


@pytest.fixture
def route(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'fixture.sqlite3'))
    SQLModel.metadata.create_all(engine)
    project = Project(id=1, slug='fixture', human_key='/fixture')
    agents = [Agent(id=i, project_id=1, name=n, program='fixture', model='fixture')
              for i, n in [(1, 'ProudTuring'), (2, 'SandyLangmuir'), (3, 'ScarletRamanujan')]]
    with Session(engine, expire_on_commit=False) as session:
        session.add(project)
        session.add_all(agents)
        session.commit()

    class AsyncAdapter:
        async def execute(self, stmt):
            return self.session.execute(stmt)

    @asynccontextmanager
    async def sessions():
        with Session(engine, expire_on_commit=False) as session:
            adapter = AsyncAdapter()
            adapter.session = session
            yield adapter

    async def ready():
        pass
    monkeypatch.setattr(app, 'get_session', sessions)
    monkeypatch.setattr(app, 'ensure_schema', ready)
    calls = []

    def transport(payload):
        if payload['method'] == 'tools/list':
            return {'result': {'tools': [{'name': 'fetch_inbox', 'inputSchema': {
                'properties': {'message_id': {}, 'registration_token': {}}}}]}}
        args = payload['params']['arguments']
        calls.append(args)
        assert args['project_key'] == '/fixture'
        assert args['registration_token'] == 'fixture-owner'
        agent = next(a for a in agents if a.name == args['agent_name'])
        rows = asyncio.run(app._list_inbox(project, agent, args['limit'],
                            args['urgent_only'], args['include_bodies'],
                            args.get('since_ts'), args.get('topic'), args.get('message_id')))
        return {'result': {'structuredContent': {'result': rows}}}

    def proxy(name):
        identities = IdentityStore(tmp_path / name)
        binding = build_binding(session_id=name, agent_id=None, agent_name=name, project_key='/fixture')
        identities.save(binding)
        identities.store_owner_token(binding['external_id'], 'fixture-owner')
        p = AgentStackProxy(identities, SnapshotStore(tmp_path / (name + '.json')), AgentMailClient(transport))
        p.bootstrap(name)
        return p

    def insert(message_id, body, *, recipient=2, kind='to', importance='normal', project_id=1):
        with Session(engine, expire_on_commit=False) as session:
            session.add(Message(id=message_id, project_id=project_id, sender_id=1,
                        subject='[station] fixture', body_md=body, importance=importance,
                        created_ts=datetime(2026, 10, 12, tzinfo=timezone.utc) + timedelta(seconds=message_id)))
            session.add(MessageRecipient(message_id=message_id, agent_id=recipient, kind=kind))
            session.commit()

    yield proxy, insert, calls
    engine.dispose()


@pytest.mark.parametrize('kind', ['to', 'cc'])
@pytest.mark.parametrize('importance', ['normal', 'high', 'urgent'])
@pytest.mark.parametrize('size', [775, 1260, 9000])
def test_exact_body_survives_long_inbox_and_recovers_all_unicode_chunks(route, kind, importance, size):
    proxy, insert, calls = route
    body = ('日本語\n🙂e\u0301' * (size // 7 + 1))[:size]
    insert(20597, body, kind=kind, importance=importance)
    for message_id in range(20600, 20630):
        insert(message_id, '新着本文' * 500)
    p = proxy('SandyLangmuir')
    bulk = p.fetch_inbox('SandyLangmuir')
    assert 20597 not in [m['id'] for m in bulk]  # truly outside the latest page
    assert sum(len(m['body_md']) for m in bulk) <= 6000
    assert all(m['body_truncated'] and str(m['id']) in m['body_retrieval'] for m in bulk)
    offset = 0
    chunks = []
    while True:
        rows = p.fetch_inbox('SandyLangmuir', message_id=20597, body_offset=offset, body_limit=333)
        assert len(rows) == 1
        m = rows[0]
        assert m['id'] == 20597 and m['kind'] == kind and m['importance'] == importance
        assert m['body_offset'] == offset and m['body_total_chars'] == len(body)
        assert len(m['body_md']) <= 333
        chunks.append(m['body_md'])
        if m['body_next_offset'] is None:
            break
        assert m['body_next_offset'] > offset
        offset = m['body_next_offset']
    assert ''.join(chunks) == body
    assert calls[-1]['message_id'] == 20597


def test_21016_default_body_is_full_and_unauthorized_recipient_cannot_read(route):
    proxy, insert, calls = route
    body = '本文' * 387 + '終'
    insert(21016, body, recipient=3)
    p = proxy('ScarletRamanujan')
    response = StdioMcpServer(p).handle({'id': 1, 'method': 'tools/call', 'params': {
        'name': 'fetch_inbox', 'arguments': {'message_id': 21016}}})
    result = response['result']
    assert not result['isError']
    assert json.loads(result['content'][0]['text'])[0]['body_md'] == body
    assert result['structuredContent']['result'][0]['body_truncated'] is False
    assert proxy('SandyLangmuir').fetch_inbox('SandyLangmuir', message_id=21016) == []
    omitted = p.fetch_inbox('ScarletRamanujan', message_id=21016, include_bodies=False)[0]
    assert omitted['body_omitted'] and '21016' in omitted['body_retrieval']


@pytest.mark.parametrize('arguments', [dict(message_id=True), dict(message_id=0),
    dict(body_offset=-1), dict(body_offset=1), dict(body_limit=0), dict(body_limit=4001)])
def test_bad_chunk_or_id_does_not_reach_transport(route, arguments):
    proxy, _, calls = route
    with pytest.raises(ProxyError):
        proxy('SandyLangmuir').fetch_inbox('SandyLangmuir', **arguments)
    assert not calls


def test_old_server_fails_exact_retrieval_explicitly():
    client = AgentMailClient(lambda request: {'result': {'tools': []}})
    with pytest.raises(AgentMailError, match='matching mail server'):
        client.fetch_inbox(project_key='/fixture', agent_name='SandyLangmuir', message_id=20597)
