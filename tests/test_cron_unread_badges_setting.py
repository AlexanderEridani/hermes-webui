"""Cron completion badges can be disabled without muting completion toasts.

The polling loop is extracted from `static/panels.js` and exercised in Node, the
same way the neighbouring cron regression tests do, so these assertions cover the
behaviour the browser actually runs instead of the source text that implements it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
NODE = shutil.which("node")

CONFIG_PY = (ROOT / "api" / "config.py").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
PANELS_JS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
SESSIONS_JS = (ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
BOOT_JS = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    brace = source.index("{", start)
    depth = 1
    pos = brace + 1
    while depth and pos < len(source):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
        pos += 1
    return source[start:pos]


def _run_node(script: str) -> dict:
    assert NODE is not None
    result = subprocess.run(
        [NODE, "-e", script], check=True, capture_output=True, text=True, timeout=30
    )
    return json.loads(result.stdout)


def _run_cron_polling(host_setup: str = "") -> dict:
    """Run one polling tick; `host_setup` optionally defines the DOM root."""
    polling = _extract_function(PANELS_JS, "startCronPolling")
    script = f"""
let _cronPollSince=10;
let _cronPollTimer=null;
let _cronUnreadCount=0;
let _cronPollGeneration=0;
const _cronNewJobIds=new Set();
const markCalls=[];
const toasts=[];
let intervalCallback=null;
global.document={{hidden:false}};
global.S={{activeProfile:'profile-a'}};
{host_setup}
global.setInterval=(callback)=>{{ intervalCallback=callback; return 1; }};
global.api=async()=>({{
  completions:[{{
    job_id:'job-a',
    session_id:'cron-session-a',
    message_count:3,
    completed_at:20,
  }}]
}});
global.showToast=(...args)=>{{ toasts.push(args); }};
global.t=(key)=>key;
global.updateCronBadge=()=>{{ _cronUnreadCount=_cronNewJobIds.size; }};
function _markSessionCompletionUnreadIfBackground(sid, count, meta){{
  markCalls.push([sid, count, meta]);
}}
{polling}
startCronPolling();
(async()=>{{
  await intervalCallback();
  process.stdout.write(JSON.stringify({{markCalls, toasts, unreadJobs:Array.from(_cronNewJobIds)}}));
}})().catch(error=>{{ console.error(error); process.exit(1); }});
"""
    return _run_node(script)


def test_cron_unread_badges_preference_is_persisted_and_applied():
    assert '"cron_unread_badges": True' in CONFIG_PY
    assert '"cron_unread_badges"' in CONFIG_PY.split("_SETTINGS_BOOL_KEYS", 1)[1]
    assert 'id="settingsCronUnreadBadges"' in INDEX_HTML
    assert "payload.cron_unread_badges=" in PANELS_JS
    assert "_cronUnreadBadgesEnabled=cronUnreadBadgesCb.checked" in PANELS_JS
    assert "_cronUnreadBadgesEnabled=s.cron_unread_badges!==false" in BOOT_JS
    # Both boot paths must leave a boolean behind: the settings-loaded path and the
    # settings-load-failed path, which mirrors the True config default (#3988).
    assert BOOT_JS.count("_cronUnreadBadgesEnabled=") == 2


def test_polling_marks_unread_when_no_dom_root_is_present():
    """A bare `window` reference throws here and the loop's catch swallows it."""
    state = _run_cron_polling()
    assert state["unreadJobs"] == ["job-a"]
    assert state["markCalls"] == [
        ["cron-session-a", 3, {"source": "cron", "profile": "profile-a"}]
    ]
    assert len(state["toasts"]) == 1


def test_enabled_badges_mark_unread_and_still_toast():
    state = _run_cron_polling("global.window={_cronUnreadBadgesEnabled:true};")
    assert state["unreadJobs"] == ["job-a"]
    assert len(state["markCalls"]) == 1
    assert len(state["toasts"]) == 1


def test_muted_cron_badges_skip_all_unread_markers_but_not_toasts():
    state = _run_cron_polling("global.window={_cronUnreadBadgesEnabled:false};")
    assert state["unreadJobs"] == []
    assert state["markCalls"] == []
    # Muting badges must not mute completion toasts.
    assert len(state["toasts"]) == 1


def test_clear_helper_drops_only_cron_markers_and_reuses_existing_renderers():
    clear_helper = _extract_function(PANELS_JS, "_clearCronUnreadMarkers")
    script = f"""
const _cronNewJobIds=new Set(['job-a','job-b']);
const calls=[];
global.updateCronBadge=()=>{{ calls.push('badge'); }};
global.$=(id)=>(id==='cronList'?{{}}:null);
global.loadCrons=()=>{{ calls.push('loadCrons'); }};
global._clearAllCronSessionCompletionUnread=()=>{{ calls.push('sessions'); }};
{clear_helper}
_clearCronUnreadMarkers();
process.stdout.write(JSON.stringify({{remaining:Array.from(_cronNewJobIds), calls}}));
"""
    state = _run_node(script)
    assert state["remaining"] == []
    assert state["calls"] == ["sessions", "badge", "loadCrons"]


def test_session_marker_clear_keeps_non_cron_markers():
    helper = _extract_function(SESSIONS_JS, "_clearAllCronSessionCompletionUnread")
    script = f"""
const store={{
  'cron-a':{{source:'cron'}},
  'chat-b':{{source:'chat'}},
  'not-an-object':'junk',
}};
const calls=[];
global._getSessionCompletionUnread=()=>store;
global._resolveCronCompletionMarkerOrigin=(sid,marker)=>({{isCron:marker.source==='cron'}});
global._saveSessionCompletionUnread=()=>{{ calls.push('save'); }};
global.renderSessionListFromCache=()=>{{ calls.push('render'); }};
{helper}
const first=_clearAllCronSessionCompletionUnread();
const second=_clearAllCronSessionCompletionUnread();
process.stdout.write(JSON.stringify({{first, second, remaining:Object.keys(store), calls}}));
"""
    state = _run_node(script)
    assert state["first"] is True
    assert state["remaining"] == ["chat-b", "not-an-object"]
    assert state["calls"] == ["save", "render"]
    # Nothing cron-shaped left: a second call must be a no-op, not a rewrite.
    assert state["second"] is False
