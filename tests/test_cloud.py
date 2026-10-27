"""雲端排程判斷 (cloud_sync.auto) 與同步假日標記邏輯。"""
import sys, os, datetime, zoneinfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db
from app.cloud_sync import decide_mode, missing_days

TZ = zoneinfo.ZoneInfo("Asia/Taipei")
def at(s): return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)

def _latest_ok():
    return db.query("SELECT MAX(date) m FROM fetch_log WHERE kind='daily' AND status='ok'")[0]["m"]

def test_auto_is_news_when_nothing_missing():
    d = datetime.date.fromisoformat(_latest_ok())
    # 最新一個已抓到的交易日當天 16:00 (當天尚未到 16:30 門檻、之前都抓齊) -> news
    mode, miss = decide_mode("auto", at(f"{d:%Y-%m-%d} 16:00"))
    assert mode == "news" and miss == []

def test_auto_becomes_full_when_a_trading_day_is_missing():
    d = datetime.date.fromisoformat(_latest_ok())
    nxt = d + datetime.timedelta(days=1)
    # 找下一個「還沒有任何抓取紀錄」的平日 (已標記為假日的跳過)
    while nxt.weekday() >= 5 or db.fetched("daily", nxt.isoformat()) is not None: nxt += datetime.timedelta(days=1)
    # 下一個交易日 17:00 還沒抓到 -> full，且缺的日期就是它
    mode, miss = decide_mode("auto", at(f"{nxt:%Y-%m-%d} 17:00"))
    assert mode == "full" and miss == [nxt.isoformat()]
    # 再隔一天早上 (補抓昨天) 也要是 full
    mode, miss = decide_mode("auto", at(f"{nxt + datetime.timedelta(days=1):%Y-%m-%d} 08:00"))
    assert mode == "full" and nxt.isoformat() in miss
    # 當天 16:30 前不算缺
    assert nxt.isoformat() not in missing_days(at(f"{nxt:%Y-%m-%d} 15:00"))

def test_fetch_failure_is_not_marked_holiday(monkeypatch):
    """抓取時發生例外 (網路/被擋) 不可標成假日，否則永遠不會重抓。"""
    from app import sync
    from app.fetch import twse, tpex
    target = datetime.date(2020, 1, 6)  # 任一過去的平日
    db.executemany("DELETE FROM fetch_log WHERE kind='daily' AND date=?", [(target.isoformat(),)])
    def boom(d): raise RuntimeError("HTTP 403")
    monkeypatch.setattr(twse, "fetch_daily", boom); monkeypatch.setattr(tpex, "fetch_daily", boom)
    monkeypatch.setattr(sync, "weekdays_back", lambda n: [target])
    sync.sync_prices()
    assert db.fetched("daily", target.isoformat()) is None
    # 交易所明確回「無資料」(None) 才標假日
    monkeypatch.setattr(twse, "fetch_daily", lambda d: None); monkeypatch.setattr(tpex, "fetch_daily", lambda d: None)
    sync.sync_prices()
    assert db.fetched("daily", target.isoformat()) == "holiday"
    db.executemany("DELETE FROM fetch_log WHERE kind='daily' AND date=?", [(target.isoformat(),)])

def test_explicit_modes_pass_through():
    assert decide_mode("news")[0] == "news" and decide_mode("full")[0] == "full"

def test_workflow_cron_avoids_top_of_hour_and_runs_every_30min():
    yml = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".github", "workflows", "update.yml"), encoding="utf-8").read()
    import re
    crons = re.findall(r'cron:\s*"([^"]+)"', yml)
    assert crons, "缺少排程"
    for c in crons:
        minute = c.split()[0]
        assert "0" not in minute.split(","), f"避免整點排程 (GitHub 常略過): {c}"
        assert len(minute.split(",")) >= 2, f"至少每 30 分鐘一次: {c}"
    assert "workflow_dispatch" in yml and "cloud_sync" in yml

def test_cloud_ai_runs_once_per_slot(monkeypatch):
    """雲端 AI 分析: 有 API 金鑰時, 盤前 (07~08 點) 與收盤後 full 各最多跑一次; 同一時段重跑不再呼叫; 沒金鑰不呼叫。"""
    import os
    from app import cloud_sync
    from app.analysis import ai
    calls = []
    def fake_worker(mode):
        calls.append(mode); ai.state["error"] = None
        db.set_meta("ai_report", {"generated": "x", "mode": mode, "bullish_stocks": []})
    monkeypatch.setattr(ai, "_worker", fake_worker)
    monkeypatch.setattr(cloud_sync.sync, "sync_intl", lambda: None); monkeypatch.setattr(cloud_sync.sync, "sync_news", lambda: None)
    monkeypatch.setattr(cloud_sync.build_static, "build", lambda: "skip")
    saved = db.get_meta("ai_slot"); saved_rep = db.get_meta("ai_report")
    try:
        db.executemany("DELETE FROM meta WHERE key='ai_slot'", [()]) if False else None
        con = db.connect(); con.execute("DELETE FROM meta WHERE key='ai_slot'"); con.commit(); con.close()
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(cloud_sync, "_taipei_now", lambda: at("2026-10-26 07:30"))
        cloud_sync.run("news"); assert calls == [], "沒有金鑰不應呼叫 AI"
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        cloud_sync.run("news"); assert calls == ["api"], "盤前第一次應呼叫"
        cloud_sync.run("news"); assert calls == ["api"], "同一盤前時段不可重複呼叫"
        monkeypatch.setattr(cloud_sync, "_taipei_now", lambda: at("2026-10-26 12:00"))
        cloud_sync.run("news"); assert calls == ["api"], "非盤前且非 full 不呼叫"
        assert db.get_meta("ai_slot") == "2026-10-26-am"
    finally:
        con = db.connect()
        con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('ai_slot',?)", (__import__("json").dumps(saved),)) if saved else con.execute("DELETE FROM meta WHERE key='ai_slot'")
        if saved_rep is not None: con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('ai_report',?)", (__import__("json").dumps(saved_rep, ensure_ascii=False),))
        con.commit(); con.close()

def test_cloud_ai_api_path_handles_bad_key(monkeypatch):
    """ai._worker('api') 走 Anthropic API: 金鑰無效時記錄錯誤、不產生報告、不丟例外 (雲端不會因此整個失敗)。"""
    from app.analysis import ai
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-invalid-key-for-test")
    saved_rep = db.get_meta("ai_report")
    ai.state.update(running=True, error=None)
    ai._worker("api")
    assert ai.state["running"] is False and ai.state["error"], ai.state
    assert db.get_meta("ai_report") == saved_rep
