from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_webui_backend_prompt_cache_hit_percent_uses_prompt_total_denominator():
    from api.usage import prompt_cache_hit_percent

    assert prompt_cache_hit_percent(100_000, 125_000) == 80
    assert prompt_cache_hit_percent(0, 125_000) is None
    assert prompt_cache_hit_percent(100, 0) is None
    assert prompt_cache_hit_percent(None, None) is None
    assert prompt_cache_hit_percent(200, 100) == 100


def test_session_compact_exposes_prompt_cache_counters():
    from api.models import Session

    session = Session(
        session_id="issue2419_cache_usage",
        workspace="/tmp",
        input_tokens=125_000,
        output_tokens=5_000,
        estimated_cost=0.44,
        cache_read_tokens=100_000,
        cache_write_tokens=5_000,
    )

    compact = session.compact()

    assert compact["cache_read_tokens"] == 100_000
    assert compact["cache_write_tokens"] == 5_000
    assert compact["cache_hit_percent"] == 80


def test_streaming_usage_payload_includes_prompt_cache_counters():
    src = (ROOT / "api" / "streaming.py").read_text()

    assert "session_cache_read_tokens" in src
    assert "session_cache_write_tokens" in src
    assert "prompt_cache_hit_percent(" in src
    assert "'cache_hit_percent':" in src
    assert "'turn_cache_hit_percent':" in src


def test_context_indicator_surfaces_cache_hit_rate():
    src = (ROOT / "static" / "ui.js").read_text()

    assert "cacheReadTok=usage.cache_read_tokens||0" in src
    assert "cacheWriteTok=usage.cache_write_tokens||0" in src
    assert "cacheHitPct=usage.cache_hit_percent" in src
    assert "t('usage_cache_hit_detail',cacheHitPct" in src
    # The footer badge reads the effective turn usage (live `_turnUsage`, or the server-persisted
    # `turn_usage` on a reloaded row) and marks a non-provider-reported amount with `~`.
    assert "const _tu=_effectiveTurnUsage(msg,mi)" in src
    assert "const _exact=_tu.cost_status==='actual'" in src
    assert "const _mark=_exact?'':'~'" in src
    assert "const cacheHitPct=_tu.cache_hit_percent" in src
    assert "t('usage_cached_percent',cacheHitPct)" in src
    assert "cacheHitPct!=null" in src
    assert "cacheReadTok/cacheTotalTok" not in src
    assert "cacheRead/cacheTotal" not in src
    assert "cacheReadTok/promptTok" not in src
    assert "cacheRead/cacheDenom" not in src


def test_cache_usage_labels_are_localized():
    src = (ROOT / "static" / "i18n.js").read_text()

    assert src.count("usage_cache_hit_detail:") == 15
    assert src.count("usage_cached_percent:") == 15
    assert "usage_cache_hit_detail: 'Cache: {0}% hit ({1} read / {2} write)'" in src
    assert "usage_cached_percent: '{0}% cached'" in src


def test_done_handler_preserves_per_turn_cache_deltas():
    src = (ROOT / "static" / "messages.js").read_text()

    assert "_prevCacheRead=(S.session&&S.session.cache_read_tokens)||0" in src
    assert "curCacheRead=d.usage.cache_read_tokens||0" in src
    assert "cache_read_tokens:Math.max(0,curCacheRead-_prevCacheRead)" in src
    assert "cache_write_tokens:Math.max(0,curCacheWrite-_prevCacheWrite)" in src
    assert "cache_hit_percent:d.usage.turn_cache_hit_percent" in src


def test_reloaded_turn_usage_deltas_tokens_like_cost():
    """Reloaded (server-persisted) rows carry SESSION-cumulative ``turn_usage.input_tokens``
    / ``output_tokens`` — the same shape as ``session_cost_usd``. The reloaded path in
    ``_effectiveTurnUsage`` must delta them into per-turn values, or every historical reply
    would show the whole session's input/output as its own. The live ``_turnUsage`` already
    carries per-turn deltas, so only the ``msg.turn_usage`` branch is at issue (#503 mirror)."""
    src = (ROOT / "static" / "ui.js").read_text()

    assert "curIn=Number(tu.input_tokens)||0" in src
    assert "curOut=Number(tu.output_tokens)||0" in src
    assert "prevIn=Number(ptu.input_tokens)||0" in src
    assert "prevOut=Number(ptu.output_tokens)||0" in src
    # Cost must delta against the PRIOR row's session_cost_usd, NOT the token delta.

    assert "prevCost=Number(ptu.session_cost_usd)||0" in src
    # token and cost baselines must gate on `session_cost_usd` (persisted rows only): live
    # ``_turnUsage`` rows carry per-turn deltas + `session_cost`, so mixing them is a unit error.


    assert "ptu.session_cost_usd!=null" in src
    assert "cur-(seenPrev?prevCost:0)" in src
    assert "input_tokens:seenPrev?Math.max(0,curIn-prevIn):curIn" in src
    assert "output_tokens:seenPrev?Math.max(0,curOut-prevOut):curOut" in src
    # The live (in-memory) `_turnUsage` already holds per-turn deltas — return unmodified.



    assert "if(msg._turnUsage) return msg._turnUsage;" in src


def test_session_total_appended_to_live_footer_too():
    """The running session total must render on EVERY usage footer, live and reloaded
    alike. The previous guard (`!msg._turnUsage && sessionCost>0`) skipped the live turn
    on the belief that some other renderer showed it — none does, so the live footer
    showed only per-reply spend until a reload."""
    src = (ROOT / "static" / "ui.js").read_text()

    # The unconditioned render (still fed only when sessionCost>0).
    assert "if(sessionCost>0){" in src
    # The old skip-guard must not come back.
    assert "!msg._turnUsage&&sessionCost>0" not in src
