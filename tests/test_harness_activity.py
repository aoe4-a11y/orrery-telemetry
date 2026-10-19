"""Pinned native UI vocabulary, active-footer boundaries and one-capture wiring."""
from types import SimpleNamespace

import pytest

from dashboard.harness_activity import parse_activity
from dashboard import server


@pytest.mark.parametrize('program,text,state', [
    ('dsh', 'ctx 19% (24k/128k)\nesc to interrupt', 'work'),
    ('dsh', 'ctx 19% (24k/128k)\nesc 中断', 'work'),
    ('dsh', '── Awaiting approval · bash ──\nAllow this operation?\n❯ 1. Yes, allow once\n'
     '↑/↓ select · Enter confirm · Esc reject\nctx 19% (24k/128k)\nesc to interrupt', 'ask'),
    ('dsh', '── ⏳ 等待审批 · bash ──\n要允许这次操作吗？\n❯ 1. 允许（仅本次）\n'
     '↑/↓/Tab 选择 · Enter 确认 · 选中拒绝后可输入理由 · Esc 拒绝', 'ask'),
    ('dsh', '📋 Question 1/2 · 1 left\nChoose a result\n'
     '↑/↓ select · Space multi-select · Enter submit · Esc cancel · Ctrl+Q to fold / click the header', 'question'),
    ('dsh', '📋 提问 · 第 1/2 题\n问题\n'
     '输入回答 · Ctrl+V 粘贴 · Enter 提交 · Esc 上一题 · Ctrl+Q 折叠 / 点标题行收起', 'question'),
    ('dsh', '▸ 📋 Question 1/2 · 1 left Choose a result\n⏸ Waiting for your answer — Ctrl+Q to expand', 'question'),
    ('dsh', '▸ 📋 提问 · 第 1/2 题 问题\n正在等你回答 — Ctrl+Q 展开', 'question'),
    ('hermes', '☤ ❯ msg=interrupt · /queue · /bg · /steer · Ctrl+C cancel\n☤ model │ 24k/128K │ 19%', 'work'),
    ('hermes', '☤ メッセージ=中断 · /queue · /bg · /steer · Ctrl+C でキャンセル', 'work'),
    ('hermes', '╭── ⚠️  Dangerous Command ──╮\n│ echo fixture │\n│ ❯ 1. Allow once │\n╰────╯\n'
     '↑/↓ to select, Enter to confirm  (39s)', 'ask'),
    ('hermes', '⚠️  危険なコマンド\n❯ 1. 今回のみ許可\n↑/↓ で選択、Enter で確定', 'ask'),
    ('hermes', 'ExampleAgent needs your input\nPick one\n'
     '↑/↓ to select, Enter to lock, Tab next question  (29s)', 'question'),
    ('hermes', 'ExampleAgent needs your input\nWhy?\ntype your answer and press Enter', 'question'),
    ('hermes', 'ExampleAgent が入力を求めています\n理由は？\n回答を入力して Enter を押してください', 'question'),
    ('hermes', 'ExampleAgent が入力を求めています\n選択\n↑/↓ で選択、Enter で確定、Tab で次の質問', 'question'),
])
def test_pinned_current_controls(program, text, state):
    assert parse_activity(text, program) == state
    styled = '\x1b[38;2;1;2;3m' + text.replace('\n', '\x1b[0m\n\x1b[1m') + '\x1b[0m'
    assert parse_activity(styled, program) == state
    # Controls in old transcript rows must not become current activity.
    assert parse_activity(text + '\nnew output' * 46, program) is None


@pytest.mark.parametrize('program,text', [
    ('dsh', 'Thinking…'), ('dsh', '? for shortcuts'),
    ('dsh', 'Awaiting approval · bash'),
    ('dsh', '↑/↓ select · Enter confirm · Esc reject'),
    ('dsh', '📋 Question 1/2\nEnter submit'),
    ('dsh', 'Awaiting approval · bash\nesc to interrupt'),
    ('dsh', '📋 Question 1/2\nesc to interrupt'),
    ('dsh', '> Awaiting approval · bash\n> ↑/↓ select · Enter confirm · Esc reject'),
    ('dsh', '↑/↓ select · Enter confirm · Esc reject\nAwaiting approval · bash'),
    ('hermes', 'Dangerous Command'),
    ('hermes', '⚠️  Dangerous Command\n↑/↓ to select, Enter to conf'),
    ('hermes', 'ExampleAgent needs your input\nmsg=interrupt · /queue · /bg · /steer · Ctrl+C cancel'),
    ('hermes', '↑/↓ to select, Enter to confirm'),
    ('hermes', 'Ask something to get started'),
    ('hermes', 'Working…'), ('hermes', 'Ctrl+C cancel'),
    ('hermes', 'ExampleAgent needs your input\nunsupported locale footer'),
    ('hermes', '⚠️  Dangerous Command\n↑/↓ to select, Enter to confirm\n' + 'new output\n' * 8),
    ('dsh', 'ctx 19% (24k/128k)'), ('hermes', '☤ model │ 24k/128K │ 19%'),
    ('claude', 'esc to interrupt'), ('codex', 'Working (2s)'),
    ('dsh', None), ('hermes', ''),
])
def test_missing_quoted_old_or_incomplete_evidence_stays_unknown(program, text):
    assert parse_activity(text, program) is None


@pytest.mark.parametrize('program,working', [
    ('dsh', 'ctx 19% (24k/128k)\nesc to interrupt'),
    ('hermes', '☤ ❯ msg=interrupt · /queue · /bg · /steer · Ctrl+C cancel\n☤ model │ 24k/128K │ 19%'),
])
def test_one_capture_cache_generation_and_unknown_transition(monkeypatch, program, working):
    server._NATIVE_CONTEXT_CACHE.clear()
    clock, text, calls = [100.0], [working], []
    monkeypatch.setattr(server.time, 'monotonic', lambda: clock[0])

    def capture(argv, **kwargs):
        calls.append(argv)
        assert argv == ['capture-pane', '-p', '-J', '-t', '=ExampleAgent', '-S', '-45']
        return SimpleNamespace(returncode=0, stdout=text[0])

    monkeypatch.setattr(server, '_tmux_run', capture)
    value = server._native_context_runtime('ExampleAgent', 1, '$1', program)
    assert value == {'ctx_used': 19, 'ctx_window': '128K', 'act_state': 'work'}
    assert server._native_context_runtime('ExampleAgent', 1, '$1', program) == value
    assert len(calls) == 1
    text[0] = 'status hidden'
    # Same session name, new generation: never reuse the old work observation.
    assert server._native_context_runtime('ExampleAgent', 2, '$2', program) == {
        'ctx_used': None, 'ctx_window': None, 'act_state': None}
    text[0] = working
    clock[0] += server._RT_TTL + 1
    assert server._native_context_runtime('ExampleAgent', 2, '$2', program)['act_state'] == 'work'
    clock[0] += server._RT_TTL + 1
    monkeypatch.setattr(server, '_tmux_run', lambda *a, **k: SimpleNamespace(returncode=1))
    assert server._native_context_runtime('ExampleAgent', 2, '$2', program) == {
        'ctx_used': None, 'ctx_window': None, 'act_state': None}


@pytest.mark.parametrize('text,state', [
    ('esc to interrupt', 'work'),
    ('Enter to select · Esc to cancel', 'question'),
    ('Press enter to confirm or esc to cancel', 'ask'),
    ('❯', 'wait'),
])
def test_existing_claude_codex_classification_is_unchanged(text, state):
    assert server._parse_runtime(text)['act_state'] == state
