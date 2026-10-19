"""Observe native activity from the current pane footer, without I/O.

Pinned formats: dsh-tui 0.16.1 ApprovalPanel/AskUserQuestionPanel/StatusLine;
Hermes d923a5eb cli_tui_mixin and bundled en/ja catalogs. These are display
observations, not authenticated events. Missing evidence stays unknown.
"""
import re

_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')
_EDGES = ' \t\xa0│┃╭╮╰╯┌┐└┘─━┏┓┗┛'
_DSH_APPROVAL = re.compile(r'(?:Awaiting approval · .+|⏳ 等待审批 · .+)')
_DSH_QUESTION = re.compile(r'(?:▸\s+)?📋 (?:Question \d+/\d+.*|提问 · 第 \d+/\d+ 题.*)')
_DSH_CONFIRM = re.compile(
    r'↑/↓(?:/Tab)? (?:select · Enter confirm · (?:on No, type a reason · )?Esc reject'
    r'|选择 · Enter 确认 · (?:选中拒绝后可输入理由 · )?Esc 拒绝)')
_DSH_ANSWER = re.compile(r'(?:Type answer|输入回答|↑/↓ (?:select|选择)) · .*Enter (?:submit|提交) · .*Esc (?:cancel|previous question|中断|上一题).*')
_DSH_FOLDED = re.compile(r'(?:⏸\s+)?(?:Waiting for your answer|正在等你回答) — .+ (?:to expand|展开)')
_HERMES_APPROVAL = re.compile(r'⚠\ufe0f?\s+(?:Dangerous Command|危険なコマンド)')
_HERMES_QUESTION = re.compile(r'.+(?: needs your input| が入力を求めています)')
_COUNTDOWN = r'(?:\s+\(\d+s\))?'
_HERMES_CONFIRM = re.compile(
    r'(?:↑/↓ to select, Enter to confirm|↑/↓ で選択、Enter で確定)' + _COUNTDOWN)
_HERMES_ANSWER = re.compile(
    r'(?:type your answer and press Enter|↑/↓ to select, Enter to lock, Tab next question'
    r'|回答を入力して Enter を押してください|↑/↓ で選択、Enter で確定、Tab で次の質問)' + _COUNTDOWN)
_HERMES_BUSY = re.compile(
    r'☤\s+(?:[❯>$#›»→]\s+)?(?:msg=interrupt · /queue · /bg · /steer · Ctrl\+C cancel'
    r'|メッセージ=中断 · /queue · /bg · /steer · Ctrl\+C でキャンセル)')


def parse_activity(text, program):
    """Return work/question/ask or None; absence never implies idle or death.

    A modal needs both its title and a current operation footer. The footer
    must be near the bottom, not just anywhere in the captured transcript.
    Native turns remain working while awaiting a modal, so modals take priority.
    """
    if program not in ('dsh', 'hermes') or not isinstance(text, str):
        return None
    rows = [row.strip(_EDGES) for row in _ANSI.sub('', text).replace('\r', '').splitlines()[-45:]]
    rows = [row for row in rows if row]
    if not rows:
        return None
    footer = rows[-6:]
    titles = rows[-36:]

    def modal(title, hint):
        # Require the title before the matching operation, not a later quoted
        # title after an old footer. Wide/long panels outside this window are unknown.
        return any(hint.fullmatch(row) and any(title.fullmatch(previous)
                   for previous in titles[:len(titles) - len(footer) + index])
                   for index, row in enumerate(footer))

    if program == 'dsh':
        if modal(_DSH_APPROVAL, _DSH_CONFIRM):
            return 'ask'
        if modal(_DSH_QUESTION, _DSH_ANSWER) or modal(_DSH_QUESTION, _DSH_FOLDED):
            return 'question'
        if any(_DSH_APPROVAL.fullmatch(row) or _DSH_QUESTION.fullmatch(row) for row in titles):
            return None
        if rows[-1] in ('esc to interrupt', 'esc 中断'):
            return 'work'
    else:
        if modal(_HERMES_APPROVAL, _HERMES_CONFIRM):
            return 'ask'
        if modal(_HERMES_QUESTION, _HERMES_ANSWER):
            return 'question'
        if any(_HERMES_APPROVAL.fullmatch(row) or _HERMES_QUESTION.fullmatch(row) for row in titles):
            return None
        if any(_HERMES_BUSY.fullmatch(row) for row in rows[-4:]):
            return 'work'
    return None
