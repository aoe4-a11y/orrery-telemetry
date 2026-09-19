"""``reply_message`` ack_required: inheritance, env default, explicit override.

Measured on 2026-09-19 (station 8380): every ``Re:`` reply inherited the
original's ``ack_required`` with no way to opt out, so ack-required threads
snowballed. ``reply_message`` now takes an optional ``ack_required``:

- explicit ``True``/``False`` always wins;
- ``None`` (the backward-compatible default) consults
  ``AGENTSTACK_REPLY_ACK_DEFAULT``: ``inherit`` (default) copies the original
  flag, ``false`` sends the reply without an ack demand;
- an unrecognised value behaves as ``inherit`` (fail-safe towards acks).

Every test runs against a private SQLite database, archive and signal root
under ``tmp_path``; nothing touches a production ORRERY Mail instance.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from agentstack_mail import app, config, db

SENDER = "BlueLake"
REPLIER = "GreenCastle"


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> None:
    monkeypatch.setenv("AGENTSTACK_MAIL_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv(
        "AGENTSTACK_MAIL_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'mail.sqlite3'}",
    )
    monkeypatch.setenv("AGENTSTACK_MAIL_STORAGE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv(
        "AGENTSTACK_MAIL_NOTIFICATIONS_SIGNALS_DIR", str(tmp_path / "signals")
    )
    monkeypatch.setenv("AGENTSTACK_MAIL_TOOLS_LOG_ENABLED", "false")
    monkeypatch.delenv("AGENTSTACK_REPLY_ACK_DEFAULT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    db.reset_database_state()
    config.clear_settings_cache()


async def _reply_round_trip(
    tmp_path: Path,
    *,
    original_ack: bool,
    reply_kwargs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Send SENDER→REPLIER with ``original_ack``, reply with ``reply_kwargs``.

    Returns (reply tool payload, the reply as seen in SENDER's inbox).
    """
    project_key = str(tmp_path / "project")
    async with Client(app.build_mcp_server()) as client:
        await client.call_tool("ensure_project", {"human_key": project_key})
        for name in (SENDER, REPLIER):
            await client.call_tool(
                "register_agent",
                {
                    "project_key": project_key,
                    "program": "claude-code",
                    "model": "test-model",
                    "name": name,
                    "task_description": "reply-ack-override test",
                },
            )
        sent = await client.call_tool(
            "send_message",
            {
                "project_key": project_key,
                "sender_name": SENDER,
                "to": [REPLIER],
                "subject": "probe",
                "body_md": "original",
                "ack_required": original_ack,
            },
        )
        sent_payload = (sent.structured_content or sent.data)["deliveries"][0]["payload"]
        assert sent_payload["ack_required"] is original_ack

        replied = await client.call_tool(
            "reply_message",
            {
                "project_key": project_key,
                "message_id": sent_payload["id"],
                "sender_name": REPLIER,
                "body_md": "reply",
                **reply_kwargs,
            },
        )
        reply_result = replied.structured_content or replied.data
        assert reply_result["reply_to"] == sent_payload["id"]
        reply_payload = reply_result["deliveries"][0]["payload"]

        inbox = await client.call_tool(
            "fetch_inbox",
            {"project_key": project_key, "agent_name": SENDER, "include_bodies": False},
        )
        # fetch_inbox returns a bare list; fastmcp wraps it as {"result": [...]}.
        messages = (inbox.structured_content or {})["result"]
        stored = next(m for m in messages if m["id"] == reply_payload["id"])
    return reply_payload, stored


def _run(tmp_path: Path, *, original_ack: bool, **reply_kwargs: Any) -> tuple[bool, bool]:
    payload, stored = asyncio.run(
        _reply_round_trip(tmp_path, original_ack=original_ack, reply_kwargs=reply_kwargs)
    )
    assert payload["subject"] == "Re: probe"
    return bool(payload["ack_required"]), bool(stored["ack_required"])


# --- backward-compatible default: inherit -------------------------------------


def test_signature_keeps_ack_required_optional_and_last() -> None:
    server = app.build_mcp_server()
    tool = asyncio.run(server.get_tool("reply_message"))
    params = inspect.signature(tool.fn).parameters
    assert "ack_required" in params
    assert params["ack_required"].default is None
    # Every pre-existing parameter is still present, so old callers keep working.
    for legacy in ("project_key", "message_id", "sender_name", "body_md", "to", "cc", "bcc", "subject_prefix", "format"):
        assert legacy in params, legacy


def test_default_inherits_true(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    assert _run(tmp_path, original_ack=True) == (True, True)


def test_default_inherits_false(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    assert _run(tmp_path, original_ack=False) == (False, False)


def test_explicit_inherit_env_keeps_original(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path, AGENTSTACK_REPLY_ACK_DEFAULT="inherit")
    assert _run(tmp_path, original_ack=True) == (True, True)


# --- env default false ---------------------------------------------------------


def test_env_false_drops_inherited_ack(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path, AGENTSTACK_REPLY_ACK_DEFAULT="false")
    assert _run(tmp_path, original_ack=True) == (False, False)


def test_env_false_explicit_true_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path, AGENTSTACK_REPLY_ACK_DEFAULT="false")
    assert _run(tmp_path, original_ack=False, ack_required=True) == (True, True)


def test_env_false_is_case_insensitive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path, AGENTSTACK_REPLY_ACK_DEFAULT=" FALSE ")
    assert _run(tmp_path, original_ack=True) == (False, False)


def test_env_false_alias_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path, AGENTSTACK_REPLY_ACK_DEFAULT="0")
    assert _run(tmp_path, original_ack=True) == (False, False)


def test_env_true_is_not_a_force_on_and_means_inherit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path, AGENTSTACK_REPLY_ACK_DEFAULT="true")
    assert _run(tmp_path, original_ack=False) == (False, False)


# --- explicit override beats inheritance -------------------------------------


def test_explicit_false_overrides_inherited_true(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    assert _run(tmp_path, original_ack=True, ack_required=False) == (False, False)


def test_explicit_true_overrides_inherited_false(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    assert _run(tmp_path, original_ack=False, ack_required=True) == (True, True)


# --- fail-safe on garbage ------------------------------------------------------


def test_unknown_env_value_falls_back_to_inherit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path, AGENTSTACK_REPLY_ACK_DEFAULT="sometimes")
    assert _run(tmp_path, original_ack=True) == (True, True)


# --- both delivery branches resolve the same flag ----------------------------
#
# The cross-project branch needs an approved AgentLink to exercise end to end
# (see test_pending_decision_d3.py); this guard checks the source so the
# local and external ``_deliver_message`` calls cannot drift apart again.


def test_both_reply_delivery_branches_use_the_resolved_flag() -> None:
    source = Path(inspect.getsourcefile(app)).read_text(encoding="utf-8")
    start = source.index("    async def reply_message(")
    end = source.index('    @mcp.tool(name="request_contact")', start)
    body = source[start:end]
    assert "ack_required=original.ack_required" not in body
    assert len(re.findall(r"ack_required=reply_ack_required,", body)) == 2
