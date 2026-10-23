"""AI 股票分析師: 透過本機 Claude Code CLI (`claude -p`) 或 Anthropic API 解讀新聞與數據，輸出 JSON 報告。
沒有 CLI / API key 時，退回規則式摘要。"""
import os, json, re, shutil, subprocess, threading, time, datetime
from .. import db
from . import market, engine

state = {"running": False, "error": None, "started": None}

def available():
    if shutil.which("claude"): return "cli"
    if os.environ.get("ANTHROPIC_API_KEY"): return "api"
    return None

def _news_block(limit=45):
    rows = db.query("SELECT source,category,title,summary,stocks,sentiment,tags,published FROM news ORDER BY published DESC LIMIT 250")
    picked, seen = [], set()
    # prioritise: has stocks or strong sentiment, mixed categories
    rows.sort(key=lambda r: (-(abs(json.loads(r["tags"] or "{}").get("score", 0)) + (3 if r["stocks"] != "[]" else 0)), -r["published"]))
    for r in rows:
        key = r["title"][:18]
        if key in seen: continue
        seen.add(key)
        t = datetime.datetime.fromtimestamp(r["published"]).strftime("%m/%d %H:%M")
        picked.append(f"- [{t}][{r['category']}][{r['source']}] {r['title']} 相關:{r['stocks']} | {r['summary'][:120]}")
        if len(picked) >= limit: break
    return "\n".join(picked)

def build_prompt():
    imp = market.intl_impact()
    intl = "\n".join(f"- {i['name']}: {i['close']} ({i['pct']:+.2f}%)" for i in imp["items"])
    tw = market.tw_summary()
    idx = "\n".join(f"- {i['date']} 加權 {i['close']} ({i['pct']:+.2f}%)" for i in tw["index"][:5] if i.get("close"))
    ins = "\n".join(f"- {i['date']} 外資 {i['foreign']:+.1f}億 投信 {i['trust']:+.1f}億 自營 {i['dealer']:+.1f}億" for i in tw["insti"][:5])
    rec = engine.recommend(25)
    recs = "\n".join(f"- {r['code']} {r['name']} 收{r['close']} ({r['chg']:+.2f}%) 成交{r.get('lots')}張 總分{r['total']} 技術:{','.join(r['signals'][:4])} 籌碼:{','.join(r['chip_signals'][:3])} 營收YoY:{r['rev_yoy']} EPS:{r['eps_q']}" for r in rec)
    chip = engine.chips_list("foreign_sudden", 12) + engine.chips_list("trust_sudden", 12)
    chips = "\n".join(f"- {r['code']} {r['name']} 外資{r['foreign']}張 投信{r['trust']}張 {','.join(r['chip_signals'][:2])}" for r in chip)
    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""你是一位資深台股分析師。現在時間 {today}。請根據以下「國際市場」「台股大盤與法人」「最新新聞」「量化篩選結果」，寫出盤前/盤後分析報告。
請只輸出一個 JSON 物件（不要 markdown 圍欄、不要其他文字），格式：
{{
 "market_view": "對台股整體看法 (2-4 句, 含國際市場對台股的影響與操作建議)",
 "stance": "偏多|中性|偏空",
 "key_events": ["影響台股的重點事件 (最多 6 條, 每條一句話, 標明利多/利空)"],
 "intl_impact": "國外市場對台股的影響分析 (2-3 句)",
 "domestic_impact": "國內消息面對台股的影響分析 (2-3 句)",
 "bullish_stocks": [{{"code":"4位代號","name":"名稱","reason":"為何看漲 (引用具體新聞/數據, 如 訂單/EPS 上修/法人大買)","catalyst":"題材一句話","horizon":"短線|波段"}}],
 "bearish_stocks": [{{"code":"","name":"","reason":""}}],
 "sectors_hot": ["熱門族群 (最多5)"],
 "sectors_cold": ["弱勢族群 (最多3)"],
 "risk": "主要風險 (1-2 句)"
}}
bullish_stocks 請列 6-10 檔，優先選新聞有明確利多(訂單、EPS/營收上修、法人大買)且量化篩選訊號佳者；代號務必是台股4位數字代號。

## 國際市場 (最新收盤)
{intl}
規則式評估: {imp['view']} (分數 {imp['score']})

## 台股大盤 / 三大法人 (億元)
{idx}
{ins}

## 最新新聞 (時間 新→舊)
{_news_block()}

## 量化篩選 (技術面+籌碼面+基本面 綜合評分 前25)
{recs}

## 外資/投信 突然大買
{chips}
"""

def _run_cli(prompt, timeout=240):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE") and k != "CLAUDE_CODE_ENTRYPOINT"}
    cmd = ["claude", "-p", "--output-format", "text"]
    exe = shutil.which("claude")
    if exe and exe.lower().endswith((".cmd", ".bat")): cmd = ["cmd", "/c", exe] + cmd[1:]
    elif exe: cmd[0] = exe
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI 失敗: {r.stderr[-500:] or r.stdout[-500:]}")
    return r.stdout

def _run_api(prompt):
    import requests
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=240,
                      headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "max_tokens": 4000,
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []))

def _parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m: raise ValueError("AI 回應中找不到 JSON")
    return json.loads(m.group(0))

def _worker(mode):
    try:
        prompt = build_prompt()
        text = _run_cli(prompt) if mode == "cli" else _run_api(prompt)
        rep = _parse(text)
        names = {r["code"]: r["name"] for r in db.query("SELECT code,name FROM stocks")}
        for s in rep.get("bullish_stocks", []) + rep.get("bearish_stocks", []):
            if s.get("code") in names and not s.get("name"): s["name"] = names[s["code"]]
        rep["generated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        rep["mode"] = mode
        db.set_meta("ai_report", rep)
    except Exception as e:
        state["error"] = str(e)
    finally:
        state["running"] = False

def start():
    if state["running"]: return "running"
    mode = available()
    if not mode: return "unavailable"
    state.update(running=True, error=None, started=datetime.datetime.now().strftime("%H:%M:%S"))
    threading.Thread(target=_worker, args=(mode,), daemon=True).start()
    return "started"

def report():
    return db.get_meta("ai_report")
