"""Regression tests for the delegated-subagent unread roll-up and family read-ack.

Two behaviors:

  1. A delegated subagent child session (raw_source 'subagent') is parent-owned
     work the user reads through the parent's summary — its transcripts are
     never visited directly, so its finished-unread state must NOT light the
     parent row's aggregated `_child_session_has_unread` dot (it would never
     clear). Streaming and attention (approval / clarify) roll-ups still bubble.

  2. The session action menu gains "Mark read (incl. subagents)" backed by
     `_markSessionFamilyRead()`, which acks the parent AND every child session
     in one action (clearing viewed counts and stale completion-unread markers).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.resolve()
SESSIONS_JS_PATH = REPO_ROOT / "static" / "sessions.js"
I18N_JS_PATH = REPO_ROOT / "static" / "i18n.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")

SESSIONS_JS = SESSIONS_JS_PATH.read_text(encoding="utf-8")
I18N_JS = I18N_JS_PATH.read_text(encoding="utf-8")


def _run_node(source: str) -> str:
    # Pass source via stdin — `-e <source>` argv is capped at MAX_ARG_STRLEN
    # and these tests embed the entire sessions.js file.
    result = subprocess.run(
        [NODE],
        input=source,
        cwd=str(REPO_ROOT),
        capture_output=True,
        encoding="utf-8",
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


_JS_EXTRACT = r"""
const src = __JS__;
function extractFunc(name) {
  const re = new RegExp('function\\s+' + name + '\\s*\\(');
  const start = src.search(re);
  if (start < 0) throw new Error(name + ' not found');
  let i = src.indexOf('{', start);
  let depth = 1; i++;
  while (depth > 0 && i < src.length) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') depth--;
    i++;
  }
  return src.slice(start, i);
}
eval(extractFunc('_isChildSession'));
eval(extractFunc('_isForkWithResolvableParent'));
eval(extractFunc('_sidebarLineageKeyForRow'));
eval(extractFunc('_attachChildSessionsToSidebarRows'));
"""


def _attach(parent, child):
    """Run _attachChildSessionsToSidebarRows over one parent + one child."""
    source = _JS_EXTRACT.replace("__JS__", repr(SESSIONS_JS)) + f"""
const parentRow = {json.dumps(parent)};
const childRow = {json.dumps(child)};
const rows = _attachChildSessionsToSidebarRows([parentRow], [parentRow, childRow]);
const out = rows.find(row => row.session_id === parentRow.session_id);
console.log(JSON.stringify({{
  hasUnread: !!out._child_session_has_unread,
  streaming: !!out._child_session_streaming,
  attention: out._child_session_attention || null,
  nestedCount: (out._child_sessions || []).length,
}}));
"""
    return json.loads(_run_node(source))


def _child(**overrides):
    base = {
        "session_id": "child-1",
        "title": "Subagent",
        "parent_session_id": "parent-1",
        "relationship_type": "child_session",
        "raw_source": "subagent",
        "source_tag": "api_server",
        "source": "api_server",
        "session_source": "api",
        "_parent_lineage_root_id": "parent-1",
        "has_unread": True,
    }
    base.update(overrides)
    return base


_PARENT = {
    "session_id": "parent-1",
    "title": "Parent chat",
    "raw_source": "api_server",
    "source_tag": "api_server",
    "session_source": "api",
}


# ── Behavior 1: delegated subagents no longer light the parent dot ──────────

def test_delegated_subagent_unread_does_not_light_parent():
    out = _attach(_PARENT, _child())
    assert out["nestedCount"] == 1, "subagent child must still nest under the parent"
    assert out["hasUnread"] is False, (
        "a delegated subagent's unread state must not light the parent's aggregated dot"
    )


def test_non_subagent_child_unread_still_lights_parent():
    out = _attach(_PARENT, _child(raw_source="api_server", source_tag="api_server", source="api_server"))
    assert out["hasUnread"] is True, (
        "a regular child session's unread state must still roll up to the parent"
    )


def test_delegated_subagent_streaming_still_lights_parent():
    out = _attach(_PARENT, _child(active_stream_id="stream-1"))
    assert out["streaming"] is True, (
        "subagent streaming state must still roll up to the parent"
    )


def test_delegated_subagent_attention_still_lights_parent():
    attention = {"kind": "clarify", "count": 1}
    out = _attach(_PARENT, _child(attention=attention))
    assert out["attention"] == attention, (
        "subagent approval/clarify attention must still roll up to the parent"
    )


# ── Behavior 2: "Mark read (incl. subagents)" menu action ───────────────────

def test_mark_session_family_read_helper_exists():
    start = SESSIONS_JS.index("function _markSessionFamilyRead")
    body = SESSIONS_JS[start:SESSIONS_JS.index("\nfunction ", start + 1)]
    assert "_setSessionViewedCount(" in body, "family read must ack each target's viewed count"
    assert "renderSessionListFromCache" in body, "family read must repaint the sidebar"
    assert "_isChildSession(s) && s.parent_session_id === sid" in body, (
        "family read must collect the parent's child sessions"
    )


def test_mark_read_children_menu_action_wired():
    assert "t('session_mark_read_children')" in SESSIONS_JS
    assert "_markSessionFamilyRead(session.session_id)" in SESSIONS_JS


def test_mark_read_children_i18n_keys_exist():
    for key in ("session_mark_read_children", "session_mark_read_children_desc"):
        assert f"{key}:" in I18N_JS, f"missing en locale key {key}"
