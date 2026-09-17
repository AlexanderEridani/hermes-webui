"""Cron completion badges can be disabled without muting completion toasts."""

from pathlib import Path


ROOT = Path(__file__).parent.parent
CONFIG_PY = (ROOT / "api" / "config.py").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
PANELS_JS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
BOOT_JS = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")


def test_cron_unread_badges_preference_is_persisted_and_applied():
    assert '"cron_unread_badges": True' in CONFIG_PY
    assert '"cron_unread_badges"' in CONFIG_PY.split("_SETTINGS_BOOL_KEYS", 1)[1]
    assert 'id="settingsCronUnreadBadges"' in INDEX_HTML
    assert "payload.cron_unread_badges=" in PANELS_JS
    assert "window._cronUnreadBadgesEnabled=cronUnreadBadgesCb.checked" in PANELS_JS
    assert "window._cronUnreadBadgesEnabled=s.cron_unread_badges!==false" in BOOT_JS


def test_muted_cron_badges_skip_all_unread_markers_but_not_toasts():
    completion_loop = PANELS_JS.split("for(const c of data.completions){", 1)[1].split("updateCronBadge();", 1)[0]
    assert "c.toast_notifications !== false" in completion_loop
    assert "if(window._cronUnreadBadgesEnabled!==false)" in completion_loop
    assert completion_loop.index("if(window._cronUnreadBadgesEnabled!==false)") < completion_loop.index("_cronNewJobIds.add")
    assert completion_loop.index("if(window._cronUnreadBadgesEnabled!==false)") < completion_loop.index("_markSessionCompletionUnreadIfBackground")
    assert "_clearCronUnreadMarkers()" in PANELS_JS
