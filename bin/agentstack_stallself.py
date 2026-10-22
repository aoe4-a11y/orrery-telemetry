"""OPS-STALL-SELF-1: at-most-once canonical mail to a stalled seat.

32536 permits SELECT of outgoing id/subject/created_ts only. No message bodies,
recipient inboxes, DB writes, pane input, supervisor or head-wait changes.
"""
import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

HOME = Path.home() / '.agentstack'
DB = HOME / 'mail/storage.sqlite3'
PROJECT = '/Users/huyuhutaru/tools/examforge'
TERMINAL = ('[receipt', '[blocked', '[env-blocked', '[terminal', '[closed', '/closed]', '[done')


def terminal_subject(subject):
    if not isinstance(subject, str):
        return False
    subject = subject.strip()
    while re.match(r'^re:\s*', subject, re.IGNORECASE):
        subject = re.sub(r'^re:\s*', '', subject, count=1, flags=re.IGNORECASE)
    return subject.casefold().startswith(TERMINAL)


def decision(message, ignored=False):
    if ignored:
        return False, 'ignored'
    if message is None:
        return False, 'no_outgoing'
    if terminal_subject(message['subject']):
        return False, 'terminal_subject'
    return True, 'nonterminal_subject'


def last_outgoing(seat, before=None, db=DB):
    # Sender filter, with no recipient filter: all outgoing recipients count.
    # Read-only URI is mandatory; never open/create a replacement database.
    uri = Path(db).resolve().as_uri() + '?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        row = con.execute(
            'SELECT m.id, m.subject, m.created_ts FROM messages m '
            'WHERE m.project_id=1 AND m.sender_id IN '
            '(SELECT id FROM agents WHERE name=?) '
            'AND (? IS NULL OR julianday(m.created_ts)<=julianday(?)) '
            'ORDER BY julianday(m.created_ts) DESC, m.id DESC LIMIT 1',
            (seat, before, before)).fetchone()
    finally:
        con.close()
    return dict(zip(('id', 'subject', 'created_ts'), row)) if row else None


def one_line(text):
    return ' '.join(str(text).splitlines()).replace('`', "'")


def notice(seat, minutes, tail, message):
    subject = (f'[progress] 席の見張り: 画面が {minutes} 分変わらない。'
               '自分の入力が要らない次の一手なら続ける・待ちなら [blocked] で何を待つかを head へ')
    body = (f'M-037・OPS-STALL-SELF-1。席 {seat}。全席CLAUDE.mdの「自分の入力が要らない工程は続ける」。\n'
            f"最後に自分が出した便: id={message['id']} 件名: {one_line(message['subject'])}\n"
            f'画面の最後の行: {one_line(tail)[:120]}\n'
            '自分で進められる次の工程は続け、待ちなら [blocked] で待つ入力を head へ返してください。')
    return dict(seat=seat, subject=subject, body_md=body)


def send_server(payload):
    # Same interpreter handoff, client and credential helper as OPS-JOBEND-1.
    if sys.version_info < (3, 10):
        result = subprocess.run(['/opt/homebrew/bin/python3', __file__, '--send-notice'],
                                input=json.dumps(payload), capture_output=True,
                                text=True, timeout=40)
        if result.returncode:
            raise RuntimeError('canonical mail client failed')
        return json.loads(result.stdout)
    sys.path.insert(0, str(HOME / 'integrations/codex_app/src'))
    from agentstack_codex_app.agent_mail_client import AgentMailClient, HttpJsonRpcTransport
    helper = HOME / 'bin/lib/agentstack-register.sh'
    token = subprocess.run(['/bin/bash', '-c', 'source "$1"; ags_load_registration_token "$2"',
                            'stallself', str(helper), 'KindPasteur'],
                           capture_output=True, text=True, timeout=10)
    if token.returncode or not token.stdout.strip():
        raise RuntimeError('operations identity credential unavailable')
    client = AgentMailClient(HttpJsonRpcTransport(
        os.environ.get('AGENTSTACK_MCP_URL', 'http://127.0.0.1:18765/mcp'),
        bearer_token=os.environ.get('MCP_AGENT_MAIL_TOKEN'), timeout=20))
    return client.send_message(project_key=PROJECT, agent_name='KindPasteur',
        registration_token=token.stdout.strip(), to=[payload['seat']],
        subject=payload['subject'], body_md=payload['body_md'], importance='normal')


def sent_id(value):
    if isinstance(value, dict):
        if isinstance(value.get('id'), int):
            return value['id']
        for key in ('deliveries', 'payload', 'result'):
            if key in value:
                found = sent_id(value[key])
                if found is not None:
                    return found
    elif isinstance(value, list):
        for row in value:
            found = sent_id(row)
            if found is not None:
                return found
    return None


def notify_self(state, path, seat, minutes, tail, dry_run=False, logger=lambda _: None,
                reader=last_outgoing, sender=send_server):
    from agentstack_jobend import save_state
    entry = state[seat]
    if entry.get('self_notice'):
        if dry_run:
            print(f'DRYRUN self skip seat={seat} reason=already_claimed')
        return 'already_claimed'
    try:
        message = reader(seat)
        allowed, reason = decision(message)
    except Exception as error:
        logger('self-read-failed seat=' + seat + ' error=' + type(error).__name__)
        if dry_run:
            print(f'DRYRUN self skip seat={seat} reason=last_outgoing_unavailable')
        return 'last_outgoing_unavailable'
    if dry_run:
        action = 'send' if allowed else 'skip'
        ident = message['id'] if message else 'none'
        print(f'DRYRUN self {action} seat={seat} last={ident} reason={reason}')
        return reason
    if not allowed:
        return reason
    # Durable claim BEFORE transport. A lost reply or restart is never retried.
    claim = dict(status='sending', last_message_id=message['id'],
                 attempted_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    entry['self_notice'] = claim
    save_state(Path(path), state)
    try:
        response = sender(notice(seat, minutes, tail, message))
        ident = sent_id(response)
        if ident is None:
            raise ValueError('canonical send did not return message id')
        claim.update(status='sent', sent_message_id=ident)
        save_state(Path(path), state)
        logger(f'self-sent seat={seat} last={message["id"]} sent={ident} count=1')
    except Exception as error:
        claim.update(status='delivery_uncertain', error_type=type(error).__name__)
        save_state(Path(path), state)
        logger('self-uncertain seat=' + seat + ' last=' + str(message['id']) +
               ' error=' + type(error).__name__)
    return claim['status']


if __name__ == '__main__' and sys.argv[1:] == ['--send-notice']:
    try:
        print(json.dumps(send_server(json.load(sys.stdin))))
    except Exception as error:
        print(type(error).__name__, file=sys.stderr)
        sys.exit(1)
