/* 台股分析師 前端 */
const $ = s => document.querySelector(s);
const STATIC = !!window.STATIC_MODE;
const api = async (p, opt) => { if (STATIC) return staticApi(p, opt); const r = await fetch(p, opt); if (!r.ok) throw new Error(p + ' ' + r.status); return r.json(); };
/* ===== 靜態模式 (GitHub Pages)：所有 API 改讀預先產生的 JSON 檔，自選股存在瀏覽器 ===== */
const _jcache = {};
async function sjson(path) { if (_jcache[path]) return _jcache[path]; const r = await fetch('api/' + path + '?t=' + Math.floor(Date.now() / 600000)); if (!r.ok) throw new Error(path + ' ' + r.status); const j = await r.json(); _jcache[path] = j; return j; }
const ML = [0, 500, 1000, 2000, 5000, 10000];
const nearML = v => { v = Number(v || 0); return ML.reduce((a, b) => Math.abs(b - v) < Math.abs(a - v) ? b : a, ML[0]); };
const lsGet = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } };
async function staticApi(p, opt) {
  const u = new URL(p, location.href); const q = u.searchParams; const path = u.pathname.replace(/^.*\/api\//, '/api/');
  const method = (opt && opt.method) || 'GET'; const ml = nearML(q.get('min_lots') || 1000);
  if (path === '/api/status') return sjson('status.json');
  if (path === '/api/overview') return sjson(`overview_${ml}.json`);
  if (path === '/api/recommend') return sjson(`recommend_${ml}.json`);
  if (path === '/api/technical') return sjson(`technical_${q.get('signal') || 'all'}_${ml}.json`);
  if (path === '/api/chips') return sjson(`chips_${q.get('kind') || 'foreign_sudden'}_${ml}.json`);
  if (path === '/api/rankings') return sjson(`rankings_${q.get('kind') || 'gainers'}_${ml}.json`);
  if (path === '/api/sectors') return sjson('sectors.json');
  if (path === '/api/backtest') return sjson('backtest.json');
  if (path === '/api/ai') return method === 'POST' ? { result: 'unavailable' } : sjson('ai.json');
  if (path === '/api/refresh' || path === '/api/tdcc_candidates') return { started: false };
  if (path === '/api/quotes') return { quotes: {}, trading: false };
  if (path === '/api/news') {
    const all = (await sjson('news.json')); const cat = q.get('cat'), sent = q.get('sent'), tag = q.get('tag'), kw = (q.get('q') || '').trim(), lim = +(q.get('limit') || 200);
    const items = all.items.filter(n => (!cat || n.category === cat) && (sent !== 'bull' || n.sentiment > 0) && (sent !== 'bear' || n.sentiment < 0)
      && (!tag || JSON.stringify(n.tags).includes(tag)) && (!kw || n.title.includes(kw) || (n.summary || '').includes(kw) || n.stocks.includes(kw))).slice(0, lim);
    return { items, updated: all.updated };
  }
  if (path === '/api/search') {
    const kw = (q.get('q') || '').trim(); if (!kw) return { items: [] };
    const all = (await sjson('stocks.json')).items; return { items: all.filter(s => s.code.startsWith(kw) || s.name.includes(kw)).slice(0, 20) };
  }
  if (path.startsWith('/api/stock/')) {
    const code = path.split('/').pop();
    try { const d = await sjson(`stock/${code}.json`); d.in_watchlist = lsGet('watchlist', []).some(w => w.code === code); return d; }
    catch (e) { return { info: { code, name: code, market: '', industry: '' }, bars: [], ind: null, insti: [], news: [], fund: null, tdcc: null, analysis: null, margin: [], quote: null, in_watchlist: false }; }
  }
  if (path.startsWith('/api/watchlist')) {
    let wl = lsGet('watchlist', []);
    if (method === 'DELETE') { lsSet('watchlist', wl.filter(w => w.code !== path.split('/').pop())); return { ok: true }; }
    if (method === 'POST') {
      const b = JSON.parse(opt.body || '{}'); const all = (await sjson('stocks.json')).items; if (!all.some(s => s.code === b.code)) throw new Error('404');
      let w = wl.find(x => x.code === b.code); if (!w) { w = { code: b.code, added: new Date().toLocaleString('sv-SE').slice(0, 16), note: '', alert_above: null, alert_below: null }; wl.push(w); }
      for (const k of ['note', 'alert_above', 'alert_below']) if (k in b) w[k] = (b[k] === '' || b[k] === null) ? null : (k === 'note' ? b[k] : +b[k]);
      lsSet('watchlist', wl); return { ok: true };
    }
    const all = (await sjson('stocks.json')).items; const byCode = Object.fromEntries(all.map(s => [s.code, s]));
    const items = await Promise.all(wl.map(async w => {
      const s = byCode[w.code] || { code: w.code, name: w.code, market: '', industry: '' }; let sig = [], csig = [], extra = {};
      try { const d = await sjson(`stock/${w.code}.json`); const a = d.analysis; if (a) { sig = a.tech.signals.map(x => x.label); csig = a.chips ? a.chips.signals.map(x => x.label) : []; extra = { foreign: a.chips && a.chips.foreign, trust: a.chips && a.chips.trust, lots: a.tech.vol / 1000 }; } } catch (e) { }
      return { ...s, ...extra, signals: sig, chip_signals: csig, quote: null, added: w.added, note: w.note, alert_above: w.alert_above, alert_below: w.alert_below };
    }));
    return { items, trading: false };
  }
  throw new Error('static: unsupported ' + p);
}
const fmt = (n, d = 2) => (n === null || n === undefined || isNaN(n)) ? '-' : Number(n).toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = n => n === null || n === undefined ? '-' : `<span class="${n > 0 ? 'up' : n < 0 ? 'dn' : 'flat'}">${n > 0 ? '+' : ''}${fmt(n)}%</span>`;
const signed = (n, d = 0) => { if (n === null || n === undefined) return '-'; const r = Math.round(n * 10 ** d) / 10 ** d; return `<span class="${r > 0 ? 'up' : r < 0 ? 'dn' : 'flat'}">${r > 0 ? '+' : ''}${fmt(r, d)}</span>`; };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const codeLink = (c, n) => `<span class="code" data-code="${c}">${c} ${esc(n || '')}</span>`;
const scoreBadge = s => `<span class="score ${s >= 50 ? 'hi' : s >= 30 ? 'mid' : ''}">${Math.round(s)}</span>`;
const amt = a => a === null || a === undefined ? '-' : a >= 1e8 ? fmt(a / 1e8, 1) + '億' : fmt(a / 1e4, 0) + '萬';
const sentBadge = s => s > 0 ? '<span class="badge bull">利多</span>' : s < 0 ? '<span class="badge bear">利空</span>' : '<span class="badge neu">中性</span>';
let toastTimer;
function toast(msg, ms = 4000) { const t = $('#toast'); t.innerHTML = msg; t.classList.remove('hidden'); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add('hidden'), ms); }
const UP = '#ff4d4f', DN = '#2ecc71';

/* ---------- 主題 ---------- */
function applyTheme(t) { document.documentElement.dataset.theme = t; $('#btnTheme').textContent = t === 'light' ? '☀️' : '🌙'; try { localStorage.setItem('theme', t); } catch (e) { } if (charts && stockData) drawCharts(stockData); }
$('#btnTheme').onclick = () => applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');

/* ---------- tabs ---------- */
const loaded = {};
const minLots = () => $('#minLots').value;
try { const v = localStorage.getItem('minLots'); if (v !== null) $('#minLots').value = v; } catch (e) { }
$('#minLots').onchange = () => { try { localStorage.setItem('minLots', minLots()); } catch (e) { } Object.keys(loaded).forEach(k => loaders[k] && loaders[k]()); };
function showTab(name) {
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.id === 'tab-' + name));
  if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  if (!loaded[name]) { loaded[name] = true; loaders[name] && loaders[name](); }
  if (name === 'stock') setTimeout(resizeCharts, 50);
}
document.querySelectorAll('nav button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
window.addEventListener('hashchange', () => { const t = location.hash.replace('#', ''); if (t && loaders[t]) showTab(t); });
document.body.addEventListener('click', e => {
  const c = e.target.closest('.code'); if (c) { openStock(c.dataset.code); return; }
  const st = e.target.closest('.star'); if (st) { toggleWatch(st.dataset.code); }
});
/* 欄位說明 */
const HELP = {
  close: '最後一個交易日的收盤價 (盤中會顯示即時價)', chg: '當日漲跌幅', lots: '當日成交張數 (1張 = 1000股)。全市場中位數約 270 張，≥1000 張屬流動性好',
  avg20: '近 20 個交易日平均成交張數，用來判斷平常的量是否足夠、進出容易', amount: '當日成交金額 (收盤價 × 股數)',
  vr: '量比 = 今日成交量 ÷ 近20日平均量。1.0x = 跟平常一樣；≥1.5x 量增；≥2x 爆量，常代表有大資金進場',
  total: '綜合評分 0~100 = 技術 40% + 籌碼 30% + 基本 15% + 新聞 15%。越高代表多項條件同時轉好；≥50 很強、30~50 偏多、<30 普通',
  tech: '技術面分數：MACD/KD 黃金交叉、站上均線、突破新高、量增價漲等訊號加總；已漲停或乖離過大會扣分',
  chip: '籌碼面分數：外資/投信突然大買、連續買超、同步買超、大戶持股增加、融資減少等加總；法人大賣、融資暴增會扣分',
  fund: '基本面分數：月營收年增率、累計營收、單季 EPS、本益比高低',
  news: '新聞面分數：近 5 日提到此股的新聞利多扣利空 (利多關鍵字 +、利空關鍵字 −)，有具體利多消息會明顯偏高',
  foreign: '外資今日買賣超張數 (+買超 / −賣超)', trust: '投信今日買賣超張數', fin: '融資餘額今日增減 (張)：融資大增代表散戶追價、籌碼變鬆；減少代表籌碼洗清',
  revyoy: '最新月營收與去年同月相比的成長率', eps: '最新一季每股盈餘 (元)',
  bias: '20日乖離 = 股價偏離月線的百分比，>15% 代表短線漲太多、容易拉回', signals: '藍=技術訊號 (右上小數字 = 該訊號歷史回測 5 日上漲機率，紅=優於大盤基準、綠=低於) 紫=籌碼訊號 綠=基本面 黃=風險提示',
};
const LEGEND = `<details><summary>欄位白話說明 (點此展開)</summary>
<b>成交(張)</b>：${HELP.lots}。<b>20日均量</b>：${HELP.avg20}。<b>量比</b>：${HELP.vr}。<br>
<b>總分</b>：${HELP.total}。<br>
<b>技術</b>：${HELP.tech}。<b>籌碼</b>：${HELP.chip}。<b>基本</b>：${HELP.fund}。<b>新聞</b>：${HELP.news}。<br>
<b>外資/投信(張)</b>：當日買賣超張數，正數買超、負數賣超。<b>融資增減</b>：${HELP.fin}。<b>營收YoY</b>：${HELP.revyoy}。<b>EPS(季)</b>：${HELP.eps}。<b>訊號</b>：${HELP.signals}。</details>`;
document.querySelectorAll('[data-legend]').forEach(el => el.innerHTML = LEGEND);

/* ---------- status polling ---------- */
let wasRunning = false, aiWaiting = false;
async function pollStatus() {
  try {
    const s = await api('/api/status');
    const bar = $('#statusBar');
    if (s.running) {
      bar.classList.remove('hidden');
      $('#statusText').textContent = `⏳ ${s.task === 'all' ? '完整同步' : '更新'}：${s.step} ${s.total ? `(${s.progress}/${s.total})` : ''}`;
      $('#statusFill').style.width = (s.total ? s.progress / s.total * 100 : 10) + '%';
      wasRunning = true;
    } else {
      bar.classList.add('hidden');
      if (wasRunning) { wasRunning = false; toast('資料更新完成'); Object.keys(loaded).forEach(k => loaders[k] && loaders[k]()); }
    }
    tradingKnown = true; liveTrading = !!s.trading; $('#liveBar').classList.toggle('hidden', !liveTrading);
    $('#dataDate').textContent = s.data_date ? `資料日 ${s.data_date} · ${s.n_stocks} 檔 · 新聞 ${s.news_updated || '-'}` : '資料初始化中…';
    if (s.ai.running) { $('#btnAI').disabled = true; $('#btnAI').textContent = '🤖 AI 分析中…'; }
    else { $('#btnAI').disabled = false; $('#btnAI').textContent = '🤖 AI 分析師解讀'; if (aiWaiting) { aiWaiting = false; loadAI(); if (s.ai.error) toast('AI 分析失敗: ' + esc(s.ai.error)); } }
  } catch (e) { }
  setTimeout(pollStatus, STATIC ? 60000 : 2500);
}
$('#btnNews').onclick = async () => { await api('/api/refresh?what=news', { method: 'POST' }); toast('開始更新新聞與國際行情'); };
$('#btnPrices').onclick = async () => { await api('/api/refresh?what=all', { method: 'POST' }); toast('開始更新行情 / 法人 / 融資券 / 基本面 / 集保'); };
$('#btnAI').onclick = async () => {
  const r = await api('/api/ai', { method: 'POST' });
  if (r.result === 'unavailable') return toast('找不到 claude CLI 或 ANTHROPIC_API_KEY，無法執行 AI 分析');
  if (r.result === 'started') { aiWaiting = true; toast('AI 分析師開始解讀，約 1–2 分鐘'); }
};

/* ---------- 即時報價 (盤中) ---------- */
let liveQuotes = {}, liveTrading = false, tradingKnown = false;
async function refreshLive(codes) {
  codes = [...new Set(codes)].filter(Boolean);
  if (!codes.length || (tradingKnown && !liveTrading)) return;  // 非交易時間不打即時報價 API
  try {
    const r = await api('/api/quotes?codes=' + codes.slice(0, 150).join(','));
    liveTrading = r.trading; Object.assign(liveQuotes, r.quotes);
    $('#liveBar').classList.toggle('hidden', !liveTrading);
    if (liveTrading) applyLive();
  } catch (e) { }
}
function applyLive() {
  document.querySelectorAll('[data-live]').forEach(el => {
    const q = liveQuotes[el.dataset.live]; if (!q || !q.live) return;
    el.innerHTML = `${fmt(q.price)} <span class="live">即時</span>`;
    const p = el.nextElementSibling; if (p && p.classList.contains('num')) p.innerHTML = pct(q.pct);
  });
}
setInterval(() => { if (!liveTrading) return; const codes = [...document.querySelectorAll('.tab.active [data-live]')].map(e => e.dataset.live); if (codes.length) refreshLive(codes); }, 10000);

/* ---------- overview ---------- */
async function loadOverview() {
  const d = await api('/api/overview?min_lots=' + minLots());
  const imp = d.impact;
  $('#impactView').className = 'impact ' + imp.cls;
  $('#impactView').innerHTML = `${esc(imp.view)} <span class="muted">(影響分數 ${imp.score > 0 ? '+' : ''}${imp.score})</span>`;
  $('#intlUpdated').textContent = imp.updated ? '更新 ' + imp.updated : '';
  const order = ['^TWII', '^SOX', 'TSM', '^IXIC', '^GSPC', '^DJI', 'NVDA', 'MU', 'AVGO', '^VIX', 'USDTWD=X', '^TNX', '^N225', '^KS11', '^HSI', 'CL=F', 'EWT'];
  $('#intlCards').innerHTML = order.filter(t => d.intl[t]).map(t => { const x = d.intl[t]; return `<div class="tile" title="${esc(x.date)}"><div class="n">${esc(x.name)}</div><div class="v">${fmt(x.close)}</div><div class="p">${pct(x.pct)} ${spark(x.hist)}</div></div>`; }).join('');
  $('#impactNotes').innerHTML = imp.notes.map(n => `<li>${esc(n)}</li>`).join('');
  const tw = d.tw;
  const insti = Object.fromEntries(tw.insti.map(i => [i.date, i]));
  $('#twTable').innerHTML = `<tr><th>日期</th><th class="num">加權指數</th><th class="num">漲跌</th><th class="num">外資</th><th class="num">投信</th><th class="num">自營</th><th class="num">合計</th></tr>` +
    tw.index.slice(0, 6).map(i => { const n = insti[i.date] || {}; return `<tr><td>${i.date}</td><td class="num">${fmt(i.close)}</td><td class="num">${pct(i.pct)}</td><td class="num">${signed(n.foreign, 1)}</td><td class="num">${signed(n.trust, 1)}</td><td class="num">${signed(n.dealer, 1)}</td><td class="num">${signed(n.total, 1)}</td></tr>`; }).join('');
  const li = r => `<li>${sentBadge(r.sentiment)}<span class="meta">${r.time} ${esc(r.source)}</span><a href="${esc(r.link)}" target="_blank">${esc(r.title)}</a> ${(r.stocks || []).map(c => `<span class="code small" data-code="${c}">${c}</span>`).join(' ')} ${(r.tags.highlights || []).map(h => `<span class="badge f">${esc(h)}</span>`).join('')}</li>`;
  $('#bullNews').innerHTML = d.bull_news.map(li).join('') || '<li class="muted">無</li>';
  $('#bearNews').innerHTML = d.bear_news.map(li).join('') || '<li class="muted">無</li>';
  $('#latestNews').innerHTML = d.latest_news.map(li).join('');
  $('#ovRec').innerHTML = `<tr><th>股票</th><th class="num">收盤</th><th class="num">漲跌</th><th class="num" title="${HELP.lots}">張數</th><th title="${HELP.total}">總分</th><th>訊號</th></tr>` +
    d.recommend.map(r => `<tr><td>${codeLink(r.code, r.name)}${star(r.code)}</td><td class="num" data-live="${r.code}">${fmt(r.close)}</td><td class="num">${pct(r.chg)}</td><td class="num">${fmt(r.lots, 0)}</td><td>${scoreBadge(r.total)}</td><td class="small">${r.reasons.slice(0, 3).map(x => `<span class="badge">${esc(x)}</span>`).join('')}</td></tr>`).join('');
  const chipT = rows => `<tr><th>股票</th><th class="num">收盤</th><th class="num">漲跌</th><th class="num" title="${HELP.lots}">張數</th><th>籌碼訊號</th></tr>` + rows.map(r => `<tr><td>${codeLink(r.code, r.name)}${star(r.code)}</td><td class="num" data-live="${r.code}">${fmt(r.close)}</td><td class="num">${pct(r.chg)}</td><td class="num">${fmt(r.lots, 0)}</td><td class="small">${r.chip_signals.slice(0, 2).map(x => `<span class="badge c">${esc(x)}</span>`).join('')}</td></tr>`).join('');
  $('#ovForeign').innerHTML = chipT(d.foreign_sudden);
  $('#ovTrust').innerHTML = chipT(d.trust_sudden);
  renderAI(d.ai);
  refreshLive([...d.recommend, ...d.foreign_sudden, ...d.trust_sudden].map(r => r.code));
}
function spark(hist) {
  if (!hist || hist.length < 5) return '';
  const v = hist.slice(-20).map(h => h.close); const mn = Math.min(...v), mx = Math.max(...v); const w = 60, h = 18;
  const pts = v.map((x, i) => `${(i / (v.length - 1) * w).toFixed(1)},${(h - (mx === mn ? h / 2 : (x - mn) / (mx - mn) * h)).toFixed(1)}`).join(' ');
  const col = v[v.length - 1] >= v[0] ? UP : DN;
  return `<svg class="ovl-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline fill="none" stroke="${col}" stroke-width="1.5" points="${pts}"/></svg>`;
}
async function loadAI() { const r = await api('/api/ai'); renderAI(r.report); }
function renderAI(a) {
  if (!a) return;
  const st = a.stance || '';
  const cls = st.includes('多') ? 'up' : st.includes('空') ? 'dn' : '';
  $('#aiMeta').textContent = `${a.generated || ''} (${a.mode === 'cli' ? 'Claude Code CLI' : 'Claude API'})`;
  $('#aiView').innerHTML = `
    <div class="stance ${cls}">立場：${esc(st)}</div>
    <p>${esc(a.market_view)}</p>
    <b>重點事件</b><ul>${(a.key_events || []).map(e => `<li>${esc(e)}</li>`).join('')}</ul>
    <p><b>國際影響：</b>${esc(a.intl_impact)}</p><p><b>國內消息：</b>${esc(a.domestic_impact)}</p>
    <b>🔥 看漲個股</b>${(a.bullish_stocks || []).map(s => `<div class="stk">${codeLink(s.code, s.name)}${star(s.code)} <span class="badge t">${esc(s.horizon || '')}</span> <span class="badge f">${esc(s.catalyst || '')}</span><div class="reasons">${esc(s.reason)}</div></div>`).join('')}
    ${(a.bearish_stocks || []).length ? `<b>⚠️ 看空/觀望</b>${a.bearish_stocks.map(s => `<div class="stk">${codeLink(s.code, s.name)}<div class="reasons">${esc(s.reason)}</div></div>`).join('')}` : ''}
    <p><b>熱門族群：</b>${(a.sectors_hot || []).map(esc).join('、')}　<b>弱勢：</b>${(a.sectors_cold || []).map(esc).join('、')}</p>
    <p class="muted">風險：${esc(a.risk)}</p>`;
}

/* ---------- news ---------- */
async function loadNews() {
  const q = new URLSearchParams({ cat: $('#newsCat').value, sent: $('#newsSent').value, q: $('#newsQ').value, tag: $('#newsTag').value, limit: 200 });
  const d = await api('/api/news?' + q);
  $('#newsUpdated').textContent = d.updated ? `共 ${d.items.length} 則 · 更新 ${d.updated}` : '';
  $('#newsList').innerHTML = d.items.map(r => `<div class="item">
    <div class="t">${sentBadge(r.sentiment)} <a href="${esc(r.link)}" target="_blank">${esc(r.title)}</a></div>
    ${r.summary ? `<div class="s">${esc(r.summary.slice(0, 220))}${r.summary.length > 220 ? '…' : ''}</div>` : ''}
    <div class="m">${r.time} · ${esc(r.source)} · ${esc(r.category)} ${r.stock_names.map(s => codeLink(s.code, s.name)).join(' ')}
      ${(r.tags.topics || []).map(t => `<span class="badge t">${esc(t)}</span>`).join('')}${(r.tags.highlights || []).map(h => `<span class="badge f">${esc(h)}</span>`).join('')}
      ${(r.tags.bull || []).map(h => `<span class="badge bull">${esc(h)}</span>`).join('')}${(r.tags.bear || []).map(h => `<span class="badge bear">${esc(h)}</span>`).join('')}</div></div>`).join('') || '<p class="muted">沒有符合的新聞</p>';
}
['#newsCat', '#newsSent', '#newsTag'].forEach(s => $(s).onchange = loadNews);
$('#newsGo').onclick = loadNews; $('#newsQ').onkeydown = e => { if (e.key === 'Enter') loadNews(); };

/* ---------- 共用列 ---------- */
let watchSet = new Set(), winMap = {};  // label -> {win, base}
async function loadFactors() { try { const d = await api('/api/technical?limit=1'); for (const [id, f] of Object.entries(d.factors || {})) { const lab = d.labels[id]; if (lab) winMap[lab] = f; } } catch (e) { } }
const sigBadge = (x, cls = 't') => { const key = x.replace(/\(.*$/, ''); const f = winMap[x] || winMap[key]; return `<span class="badge ${cls}" ${f ? `title="歷史回測：出現後 5 日上漲機率 ${f.win}% (全市場基準 ${f.base}%，樣本 ${f.n})"` : ''}>${esc(x)}${f ? `<i class="win ${f.win >= f.base + 3 ? 'g' : f.win < f.base - 3 ? 'b' : ''}">${Math.round(f.win)}%</i>` : ''}</span>`; };
const star = c => `<span class="star ${watchSet.has(c) ? 'on' : ''}" data-code="${c}" title="加入/移除自選股">${watchSet.has(c) ? '★' : '☆'}</span>`;
function stockRow(r, extra = '') {
  const td = r.tdcc && r.tdcc.d_big400 !== undefined ? `<span class="badge ${r.tdcc.d_big400 > 0 ? 'bull' : 'bear'}">大戶週${r.tdcc.d_big400 > 0 ? '+' : ''}${r.tdcc.d_big400}%</span>` : '';
  return `<tr class="row" data-code="${r.code}"><td>${codeLink(r.code, r.name)}${star(r.code)}<div class="muted">${esc(r.market)} ${esc(r.industry)}</div></td>
    <td class="num" data-live="${r.code}">${fmt(r.close)}</td><td class="num">${pct(r.chg)}</td><td class="num">${fmt(r.lots, 0)}</td><td class="num muted">${fmt(r.avg20_lots, 0)}</td><td class="num">${amt(r.amount)}</td><td class="num">${fmt(r.vol_ratio, 1)}x</td>
    <td>${scoreBadge(r.total)}</td><td class="num">${r.tech_score}</td><td class="num">${r.chip_score}</td><td class="num">${r.fund_score}</td><td class="num">${r.news_score}</td>
    <td class="num">${signed(r.foreign)}</td><td class="num">${signed(r.trust)}</td><td class="num">${signed(r.fin_change)}</td><td class="num">${r.rev_yoy === null || r.rev_yoy === undefined ? '-' : pct(r.rev_yoy)}</td><td class="num">${fmt(r.eps_q)}</td>
    <td class="small">${(r.signals || []).slice(0, 4).map(x => sigBadge(x)).join('')}${(r.chip_signals || []).slice(0, 3).map(x => `<span class="badge c">${esc(x)}</span>`).join('')}${td}${extra}</td></tr>`;
}
const HEAD = `<tr><th>股票</th><th class="num" title="${HELP.close}">收盤</th><th class="num" title="${HELP.chg}">漲跌</th><th class="num" title="${HELP.lots}">成交(張)</th><th class="num" title="${HELP.avg20}">20日均量</th><th class="num" title="${HELP.amount}">成交額</th><th class="num" title="${HELP.vr}">量比</th><th title="${HELP.total}">總分</th><th class="num" title="${HELP.tech}">技術</th><th class="num" title="${HELP.chip}">籌碼</th><th class="num" title="${HELP.fund}">基本</th><th class="num" title="${HELP.news}">新聞</th><th class="num" title="${HELP.foreign}">外資(張)</th><th class="num" title="${HELP.trust}">投信(張)</th><th class="num" title="${HELP.fin}">融資增減</th><th class="num" title="${HELP.revyoy}">營收YoY</th><th class="num" title="${HELP.eps}">EPS(季)</th><th title="${HELP.signals}">訊號</th></tr>`;
const NCOL = 18;
function bindExpand(sel) { document.querySelectorAll(sel + ' tr.row').forEach(tr => tr.onclick = e => { if (e.target.closest('.code,.star,a,input,button')) return; tr.classList.toggle('open'); }); }

/* ---------- recommend ---------- */
async function loadRecommend() {
  const d = await api('/api/recommend?limit=50&min_lots=' + minLots());
  $('#recBuilt').textContent = ` 資料日 ${d.date}，計算於 ${d.built}，共 ${d.items.length} 檔 (點表頭排序：▼大→小 / ▲小→大 / 再點取消)`;
  $('#expRec').href = '/api/export?what=recommend&min_lots=' + minLots();
  $('#recTable').innerHTML = HEAD + d.items.map(r => stockRow(r) + `<tr class="expand"><td colspan="${NCOL}"><b>推薦理由：</b>${r.reasons.map(x => `<span class="badge">${esc(x)}</span>`).join(' ')}
     ${r.risks.length ? `<br><b>風險：</b>${r.risks.map(x => `<span class="badge risk">${esc(x)}</span>`).join(' ')}` : ''}
     <br><span class="muted">趨勢 ${esc(r.trend)} (均線排列) · 20日乖離 ${fmt(r.bias20, 1)}% (股價離月線的距離，>15% 偏高) · 量比 ${fmt(r.vol_ratio, 1)}x (今日量÷20日均量) · 外資連${r.foreign_streak}日 · 投信連${r.trust_streak}日 · 本益比 ${fmt(r.pe, 1)} · 相關新聞 ${r.news_n} 則</span></td></tr>`).join('');
  bindExpand('#recTable');
  refreshLive(d.items.map(r => r.code));
}

/* ---------- technical ---------- */
async function loadTechnical() {
  const d = await api('/api/technical?signal=' + $('#techSignal').value + '&limit=100&min_lots=' + minLots());
  $('#techTable').innerHTML = HEAD + d.items.map(r => stockRow(r)).join('');
  $('#techCount').textContent = `共 ${d.items.length} 檔 (點表頭排序：▼大→小 / ▲小→大 / 再點取消)`;
  $('#expTech').href = '/api/export?what=technical&signal=' + $('#techSignal').value + '&min_lots=' + minLots();
  refreshLive(d.items.map(r => r.code));
}
$('#techSignal').onchange = loadTechnical;
$('#btnBacktest').onclick = async () => {
  const box = $('#backtestBox'); box.classList.toggle('hidden');
  if (box.classList.contains('hidden')) return;
  box.innerHTML = '<p class="muted">載入中…</p>';
  let r = (await api('/api/backtest')).report;
  if (!r) r = (await api('/api/backtest', { method: 'POST' })).report;
  const hz = ['1', '3', '5', '10'];
  const cell = (v, base) => v ? `<td class="${v.win >= (base ? base.win + 3 : 55) ? 'good' : v.win < (base ? base.win - 3 : 45) ? 'bad' : ''}">${v.win}% <span class="muted">(${v.avg > 0 ? '+' : ''}${v.avg}%)</span></td>` : '<td>-</td>';
  const rows = Object.entries(r.signals).sort((a, b) => ((b[1]['5'] || {}).win || 0) - ((a[1]['5'] || {}).win || 0));
  box.innerHTML = `<h2>📈 訊號勝率回測 <span class="muted">以本機 ${r.dates[0]} ~ ${r.dates[1]} 共 ${r.n_stocks} 檔 (均量≥${r.min_lots}張) 歷史資料，統計訊號出現後 N 日收盤報酬為正的比例與平均報酬。勝率明顯高於「基準 (任一天)」才有參考價值。</span></h2>
    <table class="tbl bt"><tr><th>訊號</th><th>樣本數</th>${hz.map(h => `<th>${h}日後勝率 (平均)</th>`).join('')}</tr>
    <tr><td><b>基準：隨機任一天</b></td><td>${fmt(r.base['5'].n, 0)}</td>${hz.map(h => cell(r.base[h], null)).join('')}</tr>
    ${rows.map(([id, v]) => `<tr><td>${esc(v.label)}</td><td>${v['5'] ? fmt(v['5'].n, 0) : '-'}</td>${hz.map(h => cell(v[h], r.base[h])).join('')}</tr>`).join('')}</table>
    <p class="muted">紅字 = 勝率高於基準 3 個百分點以上；綠字 = 低於基準。產生於 ${r.generated}，耗時 ${r.elapsed}s。歷史樣本有限，僅供參考。</p>`;
};

/* ---------- chips ---------- */
async function loadChips() {
  const d = await api('/api/chips?kind=' + $('#chipKind').value + '&limit=80&min_lots=' + minLots());
  $('#chipMeta').textContent = `資料日 ${d.date} · 集保週資料 ${d.tdcc_date || '-'} · 共 ${d.items.length} 檔 (點表頭排序：▼大→小 / ▲小→大 / 再點取消)`;
  $('#expChips').href = '/api/export?what=chips&kind=' + $('#chipKind').value + '&min_lots=' + minLots();
  $('#chipTable').innerHTML = HEAD + d.items.map(r => stockRow(r)).join('') || '<tr><td>無符合</td></tr>';
  refreshLive(d.items.map(r => r.code));
}
$('#chipKind').onchange = loadChips;
$('#btnTdcc').onclick = async () => { const r = await api('/api/tdcc_candidates', { method: 'POST' }); toast(r.started ? '開始查詢集保大戶週變化（約 1 分鐘）' : '目前有其他更新進行中'); };

/* ---------- rankings / sectors ---------- */
async function loadRankings() {
  const kind = $('#rankKind').value;
  const d = await api('/api/rankings?kind=' + kind + '&limit=60&min_lots=' + minLots());
  $('#rankMeta').textContent = `資料日 ${d.date} · 共 ${d.items.length} 檔`;
  $('#expRank').href = '/api/export?what=rankings&kind=' + kind + '&min_lots=' + minLots();
  $('#rankTable').innerHTML = HEAD + d.items.map(r => stockRow(r)).join('');
  refreshLive(d.items.map(r => r.code));
  if (!loadRankings.sectorsDone) { loadRankings.sectorsDone = true; loadSectors(); }
}
$('#rankKind').onchange = loadRankings;
async function loadSectors() {
  const d = await api('/api/sectors');
  const col = c => { const a = Math.min(1, Math.abs(c) / 3); return c > 0 ? `rgba(215,38,61,${0.25 + a * 0.7})` : c < 0 ? `rgba(26,156,87,${0.25 + a * 0.7})` : 'rgba(120,130,140,.4)'; };
  $('#sectorMap').innerHTML = d.items.map((s, i) => `<div class="cell" data-i="${i}" style="background:${col(s.w_chg)}" title="${esc(s.industry)}：${s.n} 檔，上漲 ${s.up} 下跌 ${s.down}"><div class="n">${esc(s.industry)}</div><div class="v">${s.w_chg > 0 ? '+' : ''}${s.w_chg}%</div><div class="m">${s.up}↑ ${s.down}↓ · ${amt(s.amount)}</div></div>`).join('');
  $('#sectorTable').innerHTML = `<tr><th>產業</th><th class="num">加權漲幅</th><th class="num">平均</th><th class="num">漲/跌家數</th><th class="num">成交額</th><th class="num">外資(億)</th><th>龍頭股 (成交額前5)</th></tr>` +
    d.items.map(s => `<tr><td>${esc(s.industry)}</td><td class="num">${pct(s.w_chg)}</td><td class="num">${pct(s.avg_chg)}</td><td class="num">${s.up}/${s.down}</td><td class="num">${amt(s.amount)}</td><td class="num">${signed(s.foreign_amt / 1e8, 1)}</td><td class="small">${s.top.map(t => `${codeLink(t.code, t.name)} ${pct(t.chg)}`).join('　')}</td></tr>`).join('');
  $('#sectorMap').onclick = e => { const c = e.target.closest('.cell'); if (!c) return; const s = d.items[+c.dataset.i]; toast(`<b>${esc(s.industry)}</b> 龍頭股：${s.top.map(t => `${codeLink(t.code, t.name)} ${pct(t.chg)}`).join('　')}`, 8000); };
}

/* ---------- watchlist ---------- */
async function loadWatchlist() {
  const d = await api('/api/watchlist');
  watchSet = new Set(d.items.map(i => i.code)); $('#wlCount').textContent = d.items.length || '';
  liveTrading = d.trading; $('#liveBar').classList.toggle('hidden', !liveTrading);
  $('#wlMeta').textContent = `共 ${d.items.length} 檔${d.trading ? ' · 盤中即時更新' : ' · 非交易時間 (顯示收盤價)'}`;
  if (!d.items.length) { $('#wlTable').innerHTML = '<tr><td class="muted">尚無自選股。在任何表格點 ☆ 或在上方輸入代號加入。</td></tr>'; return; }
  $('#wlTable').innerHTML = `<tr><th>股票</th><th class="num">現價</th><th class="num">漲跌</th><th class="num">成交(張)</th><th class="num">總分</th><th class="num">外資</th><th class="num">投信</th><th>提醒</th><th>備註</th><th>訊號</th><th></th></tr>` +
    d.items.map(r => {
      const q = r.quote; const price = q && q.live ? q.price : r.close; const chg = q && q.live ? q.pct : r.chg;
      const hitUp = r.alert_above && price >= r.alert_above, hitDn = r.alert_below && price <= r.alert_below;
      if (q && q.live) liveQuotes[r.code] = q;
      return `<tr class="row ${hitUp || hitDn ? 'alert-hit' : ''}" data-code="${r.code}"><td>${codeLink(r.code, r.name)}<div class="muted">${esc(r.market)} ${esc(r.industry)}</div></td>
        <td class="num" data-live="${r.code}">${fmt(price)} ${q && q.live ? '<span class="live">即時</span>' : ''}</td><td class="num">${pct(chg)}</td><td class="num">${fmt(q && q.live ? q.volume : r.lots, 0)}</td>
        <td class="num">${r.total ? scoreBadge(r.total) : '-'}</td><td class="num">${signed(r.foreign)}</td><td class="num">${signed(r.trust)}</td>
        <td class="small">${r.alert_above ? `<span class="badge ${hitUp ? 'bull' : ''}">≥ ${r.alert_above}${hitUp ? ' 已達' : ''}</span>` : ''}${r.alert_below ? `<span class="badge ${hitDn ? 'bear' : ''}">≤ ${r.alert_below}${hitDn ? ' 已達' : ''}</span>` : ''}</td>
        <td class="small">${esc(r.note || '')}</td><td class="small">${(r.signals || []).slice(0, 3).map(x => `<span class="badge t">${esc(x)}</span>`).join('')}${(r.chip_signals || []).slice(0, 2).map(x => `<span class="badge c">${esc(x)}</span>`).join('')}</td>
        <td><button class="sec wl-del" data-code="${r.code}" title="移除">✕</button></td></tr>
        <tr class="expand"><td colspan="11"><div class="wlform">提醒：高於 <input type="number" step="0.01" class="wl-above" value="${r.alert_above ?? ''}"> 低於 <input type="number" step="0.01" class="wl-below" value="${r.alert_below ?? ''}"> 備註 <input class="wl-note" style="width:260px" value="${esc(r.note || '')}"> <button class="primary wl-save" data-code="${r.code}">儲存</button> <span class="muted">加入於 ${esc(r.added)}</span></div></td></tr>`;
    }).join('');
  bindExpand('#wlTable');
  document.querySelectorAll('.wl-del').forEach(b => b.onclick = async () => { await api('/api/watchlist/' + b.dataset.code, { method: 'DELETE' }); watchSet.delete(b.dataset.code); toast('已移除'); loadWatchlist(); });
  document.querySelectorAll('.wl-save').forEach(b => b.onclick = async () => {
    const tr = b.closest('tr');
    await api('/api/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: b.dataset.code, alert_above: tr.querySelector('.wl-above').value, alert_below: tr.querySelector('.wl-below').value, note: tr.querySelector('.wl-note').value }) });
    toast('已儲存'); loadWatchlist();
  });
  checkAlerts(d.items);
}
const alerted = new Set();
function checkAlerts(items) {
  items.forEach(r => {
    const q = r.quote; const price = q && q.live ? q.price : null; if (!price) return;
    const dir = r.alert_above && price >= r.alert_above ? 'up' : r.alert_below && price <= r.alert_below ? 'dn' : '';
    if (!dir) return;
    const key = r.code + ':' + dir;
    if (!alerted.has(key)) {
      alerted.add(key); const msg = `${r.code} ${r.name} 現價 ${price} 已${dir === 'up' ? '高於' : '低於'}提醒價`;
      toast('🔔 ' + msg, 10000);
      try { if (Notification.permission === 'granted') new Notification('台股分析師 價格提醒', { body: msg }); else if (Notification.permission !== 'denied') Notification.requestPermission(); } catch (e) { }
    }
  });
}
async function toggleWatch(code) {
  if (watchSet.has(code)) { await api('/api/watchlist/' + code, { method: 'DELETE' }); watchSet.delete(code); toast(`${code} 已從自選股移除`); }
  else { try { await api('/api/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) }); } catch (e) { return toast('找不到此代號'); } watchSet.add(code); toast(`${code} 已加入自選股`); }
  document.querySelectorAll(`.star[data-code="${code}"]`).forEach(s => { s.classList.toggle('on', watchSet.has(code)); s.textContent = watchSet.has(code) ? '★' : '☆'; });
  $('#wlCount').textContent = watchSet.size || '';
  if (loaded.watchlist) loadWatchlist();
  updateWlToggle(code);
}
$('#wlAdd').onclick = () => searchStock($('#wlInput').value.trim(), async c => { if (!watchSet.has(c)) await toggleWatch(c); $('#wlInput').value = ''; });
$('#wlInput').onkeydown = e => { if (e.key === 'Enter') $('#wlAdd').onclick(); };
setInterval(() => { if (loaded.watchlist && document.querySelector('#tab-watchlist').classList.contains('active') && liveTrading) loadWatchlist(); }, 10000);

/* ---------- stock / charts ---------- */
let charts = null, stockData = null, period = 'D';
const overlays = { ma: true, bb: true, insti: true };
try { Object.assign(overlays, JSON.parse(localStorage.getItem('overlays') || '{}')); period = localStorage.getItem('period') || 'D'; } catch (e) { }
function syncSegButtons() {
  document.querySelectorAll('#period button').forEach(b => b.classList.toggle('on', b.dataset.p === period));
  document.querySelectorAll('#overlays button').forEach(b => b.classList.toggle('on', !!overlays[b.dataset.k]));
}
$('#period').onclick = e => { const b = e.target.closest('button'); if (!b) return; period = b.dataset.p; try { localStorage.setItem('period', period); } catch (x) { } syncSegButtons(); if (stockData) drawCharts(stockData); };
$('#overlays').onclick = e => { const b = e.target.closest('button'); if (!b) return; overlays[b.dataset.k] = !overlays[b.dataset.k]; try { localStorage.setItem('overlays', JSON.stringify(overlays)); } catch (x) { } syncSegButtons(); if (stockData) drawCharts(stockData); };
syncSegButtons();
function themeColors() { const light = document.documentElement.dataset.theme === 'light'; return { bg: light ? '#ffffff' : '#171d26', text: light ? '#5f6b7a' : '#8b98a9', grid: light ? '#eef1f5' : '#202a36', border: light ? '#d6dce4' : '#2a3441' }; }
function mkChart(el, h) {
  const t = themeColors();
  return LightweightCharts.createChart(el, {
    height: h, layout: { background: { color: t.bg }, textColor: t.text }, grid: { vertLines: { color: t.grid }, horzLines: { color: t.grid } },
    rightPriceScale: { borderColor: t.border, minimumWidth: 70 }, timeScale: { borderColor: t.border, timeVisible: false }, crosshair: { mode: 0 }, localization: { locale: 'zh-TW' }
  });
}
function resizeCharts() { if (!charts) return; for (const c of charts.all) c.applyOptions({ width: $('#chartMain').clientWidth }); }
window.addEventListener('resize', resizeCharts);
function syncCharts(all) {
  all.forEach(c => c.timeScale().subscribeVisibleLogicalRangeChange(r => { if (!r) return; all.forEach(o => { if (o !== c) o.timeScale().setVisibleLogicalRange(r); }); }));
}
function drawCharts(d) {
  if (charts) { charts.all.forEach(c => { try { c.remove(); } catch (e) { } }); charts = null; }
  ['#chartMain', '#chartVol', '#chartInsti', '#chartMacd', '#chartKd'].forEach(s => $(s).innerHTML = '');
  const useW = period === 'W' && d.weekly && d.weekly.bars.length >= 2;
  const bars = useW ? d.weekly.bars : d.bars, ind = useW ? d.weekly.ind : d.ind;
  const w = $('#chartMain').clientWidth;
  const main = mkChart($('#chartMain'), 380), vol = mkChart($('#chartVol'), 110), macd = mkChart($('#chartMacd'), 140), kd = mkChart($('#chartKd'), 140);
  const showInsti = overlays.insti && !useW && d.insti && d.insti.length;
  $('#chartInsti').style.display = showInsti ? '' : 'none';
  const insti = showInsti ? mkChart($('#chartInsti'), 100) : null;
  const all = [main, vol, macd, kd].concat(insti ? [insti] : []);
  all.forEach(c => c.applyOptions({ width: w }));
  const cs = main.addCandlestickSeries({ upColor: UP, downColor: DN, borderUpColor: UP, borderDownColor: DN, wickUpColor: UP, wickDownColor: DN });
  cs.setData(bars);
  const t = bars.map(b => b.time);
  const line = (chart, arr, color, lw = 1) => { const s = chart.addLineSeries({ color, lineWidth: lw, priceLineVisible: false, lastValueVisible: false }); s.setData(arr.map((v, i) => v === null ? null : { time: t[i], value: v }).filter(Boolean)); return s; };
  if (ind && overlays.ma) { line(main, ind.ma5, '#f5a623'); line(main, ind.ma10, '#4ea1ff'); line(main, ind.ma20, '#b47cff', 2); line(main, ind.ma60, '#2ecc71'); }
  if (ind && overlays.bb) { line(main, ind.bb_up, '#55637a'); line(main, ind.bb_dn, '#55637a'); }
  const vs = vol.addHistogramSeries({ priceFormat: { type: 'volume' }, priceLineVisible: false });
  vs.setData(bars.map((b, i) => ({ time: b.time, value: b.volume, color: (i > 0 && b.close >= bars[i - 1].close) ? 'rgba(255,77,79,.6)' : 'rgba(46,204,113,.6)' })));
  if (ind) {
    line(vol, ind.vma5.map(v => v === null ? null : v / 1000), '#f5a623'); line(vol, ind.vma20.map(v => v === null ? null : v / 1000), '#b47cff');
    const hs = macd.addHistogramSeries({ priceLineVisible: false });
    hs.setData(ind.osc.map((v, i) => v === null ? null : { time: t[i], value: v, color: v >= 0 ? 'rgba(255,77,79,.7)' : 'rgba(46,204,113,.7)' }).filter(Boolean));
    line(macd, ind.dif, '#f5a623'); line(macd, ind.dea, '#4ea1ff');
    line(kd, ind.k, '#f5a623'); line(kd, ind.d, '#4ea1ff'); line(kd, ind.rsi, '#b47cff');
    [80, 20].forEach(lv => { const g = kd.addLineSeries({ color: '#55637a', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }); g.setData(t.map(x => ({ time: x, value: lv }))); });
  }
  if (insti) {
    const by = Object.fromEntries(d.insti.map(r => [r.date, r]));
    const fs = insti.addHistogramSeries({ priceLineVisible: false, priceFormat: { type: 'volume' } });
    fs.setData(t.filter(x => by[x]).map(x => ({ time: x, value: by[x].foreign, color: by[x].foreign >= 0 ? 'rgba(255,77,79,.7)' : 'rgba(46,204,113,.7)' })));
    const ts = insti.addHistogramSeries({ priceLineVisible: false, priceFormat: { type: 'volume' } });
    ts.setData(t.filter(x => by[x]).map(x => ({ time: x, value: by[x].trust, color: by[x].trust >= 0 ? 'rgba(180,124,255,.8)' : 'rgba(85,99,122,.8)' })));
  }
  syncCharts(all);
  main.timeScale().fitContent();
  charts = { all };
  const idx = Object.fromEntries(t.map((x, i) => [x, i]));
  const showOhlc = i => { const b = bars[i]; if (!b) return; const prev = bars[i - 1]; const ch = prev ? (b.close / prev.close - 1) * 100 : 0;
    $('#ohlc').innerHTML = `<b>${b.time}</b>　開 ${fmt(b.open)}　高 ${fmt(b.high)}　低 ${fmt(b.low)}　收 <b class="${ch >= 0 ? 'up' : 'dn'}">${fmt(b.close)}</b> ${pct(ch)}　量 ${fmt(b.volume, 0)} 張${ind && ind.ma20[i] !== null ? `　MA20 ${fmt(ind.ma20[i])}　K ${fmt(ind.k[i], 1)} D ${fmt(ind.d[i], 1)}　DIF ${fmt(ind.dif[i])}` : ''}`; };
  main.subscribeCrosshairMove(p => { if (p && p.time && idx[p.time] !== undefined) showOhlc(idx[p.time]); });
  showOhlc(bars.length - 1);
  $('#chartLegend').innerHTML = `${useW ? '週K' : '日K'} · <span style="color:#f5a623">MA5</span> <span style="color:#4ea1ff">MA10</span> <span style="color:#b47cff">MA20</span> <span style="color:#2ecc71">MA60</span> <span style="color:#55637a">布林通道</span> · 成交量(張) ${showInsti ? '· 法人買賣超: <span style="color:#ff4d4f">外資</span> <span style="color:#b47cff">投信</span> (張)' : ''} · 滑鼠移到 K 棒可看 OHLC`;
}
function updateWlToggle(code) { const b = $('#wlToggle'); if (!stockData || stockData.info.code !== code) return; b.classList.remove('hidden'); b.textContent = watchSet.has(code) ? '★ 已在自選 (點擊移除)' : '☆ 加入自選'; }
$('#wlToggle').onclick = () => { if (stockData) toggleWatch(stockData.info.code); };
async function openStock(code) {
  showTab('stock');
  window.scrollTo(0, 0);
  $('#stockInput').value = code;
  $('#stockTitle').textContent = '載入中…';
  const d = await api('/api/stock/' + code);
  stockData = d;
  const a = d.analysis, t = a && a.tech, ch = a && a.chips, f = d.fund, td = d.tdcc, q = d.quote;
  const live = q && q.live ? `<span class="${q.pct > 0 ? 'up' : q.pct < 0 ? 'dn' : ''}">${fmt(q.price)} (${q.pct > 0 ? '+' : ''}${q.pct}%)</span> <span class="live">即時 ${esc(q.time || '')}</span>` : (t ? `<span class="${t.chg > 0 ? 'up' : t.chg < 0 ? 'dn' : ''}">${fmt(t.close)} (${t.chg > 0 ? '+' : ''}${t.chg}%)</span>` : '');
  $('#stockTitle').innerHTML = `${esc(d.info.code)} ${esc(d.info.name)} <span class="muted">${esc(d.info.market)} ${esc(d.info.industry)}</span> ${live}`;
  if (d.in_watchlist) watchSet.add(code); else watchSet.delete(code);
  updateWlToggle(code);
  if (!d.bars.length) { $('#stockInfo').innerHTML = '<p class="muted">查無資料</p>'; return; }
  drawCharts(d);
  const kv = (k, v) => `<b>${k}</b><span>${v}</span>`;
  let html = '';
  if (t) {
    html += `<h3>綜合評分 ${scoreBadge(a.total)} <span class="muted">0~100，≥50 很強、30~50 偏多</span></h3><div class="kv">${kv('技術面', `${t.tech_score} <span class="muted">(佔40%，訊號越多越高)</span>`)}${kv('籌碼面', `${ch ? ch.chip_score : '-'} <span class="muted">(佔30%，法人/大戶買進)</span>`)}${kv('基本面', `${a.fund_score} <span class="muted">(佔15%，營收/EPS/本益比)</span>`)}${kv('新聞面', `${a.news_score} <span class="muted">(佔15%，近5日利多−利空)</span>`)}</div>
      <h3>技術面 (${esc(t.trend)}) ${t.tech_score_raw !== undefined && t.tech_score_raw !== t.tech_score ? `<span class="muted">原始 ${t.tech_score_raw} → 依歷史勝率校正 ${t.tech_score}</span>` : ''}</h3><div>${t.signals.map(s => sigBadge(s.label)).join('')}${t.notes.map(s => `<span class="badge risk">${esc(s)}</span>`).join('')}</div>
      <div class="kv" style="margin-top:6px">${kv('MA5/10/20/60', `${fmt(t.ma5)} / ${fmt(t.ma10)} / ${fmt(t.ma20)} / ${fmt(t.ma60)}`)}${kv('MACD', `DIF ${fmt(t.dif)} · MACD ${fmt(t.dea)} · OSC ${fmt(t.osc)}`)}${kv('KD / RSI', `K ${fmt(t.k, 1)} D ${fmt(t.d, 1)} · RSI ${fmt(t.rsi, 1)}`)}${kv('成交張數', `${fmt(t.vol / 1000, 0)} 張 <span class="muted">(20日均 ${fmt(d.bars.slice(-20).reduce((x, b) => x + b.volume, 0) / Math.min(20, d.bars.length), 0)} 張)</span>`)}${kv('量比', `${fmt(t.vol_ratio, 1)}x <span class="muted">今日量÷20日均量，≥1.5x 量增、≥2x 爆量</span>`)}${kv('20日乖離', `${fmt(t.bias20, 1)}% <span class="muted">股價離月線距離，>15% 短線過熱</span>`)}${kv('20日高/低', `${fmt(t.high20)} / ${fmt(t.low20)}`)}</div>`;
  }
  if (ch) html += `<h3>籌碼面</h3><div>${ch.signals.map(s => `<span class="badge ${s.w < 0 ? 'risk' : 'c'}">${esc(s.label)}</span>`).join('') || '<span class="muted">無特殊訊號</span>'}</div>
      <div class="kv" style="margin-top:6px">${kv('外資 今/5日/20日', `${signed(ch.foreign)} / ${signed(ch.foreign5)} / ${signed(ch.foreign20)} 張`)}${kv('投信 今/5日/20日', `${signed(ch.trust)} / ${signed(ch.trust5)} / ${signed(ch.trust20)} 張`)}${kv('自營 今', `${signed(ch.dealer)} 張`)}${ch.margin ? kv('融資餘額', `${fmt(ch.margin.fin_balance, 0)} 張 (今 ${signed(ch.margin.fin_change)} / 5日 ${signed(ch.margin.fin_change5)})`) + kv('融券餘額', `${fmt(ch.margin.short_balance, 0)} 張 (今 ${signed(ch.margin.short_change)})`) : ''}</div>`;
  if (td) html += `<h3>集保大戶 (${td.latest.date})</h3><div class="kv">${kv('≥1000張 持股', `${td.latest.big1000}% ${td.d_big1000 !== undefined ? '(週' + signed(td.d_big1000, 2) + '%)' : ''}`)}${kv('≥400張 持股', `${td.latest.big400}% ${td.d_big400 !== undefined ? '(週' + signed(td.d_big400, 2) + '%)' : ''}`)}${kv('散戶(<10張)', `${td.latest.retail}% ${td.d_retail !== undefined ? '(週' + signed(td.d_retail, 2) + '%)' : ''}`)}${kv('股東人數', `${fmt(td.latest.holders, 0)} ${td.d_holders !== undefined ? '(' + signed(td.d_holders) + ')' : ''}`)}</div>`;
  if (f) html += `<h3>基本面</h3><div class="kv">${kv('月營收', `${f.rev_month ? (parseInt(f.rev_month.slice(0, -2)) + 1911) + '/' + f.rev_month.slice(-2) : ''} ${f.rev ? fmt(f.rev / 100000, 2) + '億' : '-'}`)}${kv('營收 MoM / YoY', `${pct(f.rev_mom)} / ${pct(f.rev_yoy)}`)}${kv('累計營收 YoY', pct(f.rev_cum_yoy))}${kv('最新季 EPS', `${fmt(f.eps_q)} 元 (${f.eps_year || ''}Q${f.eps_season || ''})`)}${kv('本益比 / 淨值比', `${fmt(f.pe, 1)} / ${fmt(f.pb, 2)}`)}${kv('殖利率', `${fmt(f.yield)}%`)}</div>
      <div>${a ? a.fund_why.map(s => `<span class="badge f">${esc(s)}</span>`).join('') : ''}</div>`;
  $('#stockInfo').innerHTML = html || '<p class="muted">資料不足 (需 30 個交易日以上)</p>';
  $('#stockInsti').innerHTML = `<tr><th>日期</th><th class="num">外資</th><th class="num">投信</th><th class="num">自營</th></tr>` + d.insti.map(r => `<tr><td>${r.date}</td><td class="num">${signed(r.foreign)}</td><td class="num">${signed(r.trust)}</td><td class="num">${signed(r.dealer)}</td></tr>`).join('');
  $('#stockMargin').innerHTML = `<tr><th>日期</th><th class="num">融資餘額</th><th class="num">增減</th><th class="num">融券餘額</th><th class="num">增減</th></tr>` + ((d.margin || []).map(r => `<tr><td>${r.date}</td><td class="num">${fmt(r.fin_balance, 0)}</td><td class="num">${signed(r.fin_change)}</td><td class="num">${fmt(r.short_balance, 0)}</td><td class="num">${signed(r.short_change)}</td></tr>`).join('') || '<tr><td class="muted">無資料</td></tr>');
  $('#stockNews').innerHTML = d.news.map(r => `<li>${sentBadge(r.sentiment)}<span class="meta">${r.time} ${esc(r.source)}</span><a href="${esc(r.link)}" target="_blank">${esc(r.title)}</a>${(r.tags.highlights || []).map(h => `<span class="badge f">${esc(h)}</span>`).join('')}</li>`).join('') || '<li class="muted">近期無相關新聞</li>';
}
async function searchStock(q, cb) {
  if (!q) return;
  if (/^\d{4}$/.test(q)) return cb(q);
  const r = await api('/api/search?q=' + encodeURIComponent(q));
  if (r.items.length) cb(r.items[0].code); else toast('找不到股票');
}
$('#stockGo').onclick = () => searchStock($('#stockInput').value.trim(), openStock);
$('#stockInput').onkeydown = e => { if (e.key === 'Enter') $('#stockGo').onclick(); };
const qs = $('#quickSearch'), box = $('#searchBox');
let qt;
qs.oninput = () => { clearTimeout(qt); qt = setTimeout(async () => { const q = qs.value.trim(); if (!q) return box.classList.add('hidden'); const r = await api('/api/search?q=' + encodeURIComponent(q)); box.innerHTML = r.items.map(i => `<div data-code="${i.code}">${i.code} ${esc(i.name)} <span class="muted">${esc(i.market)} ${i.close ? fmt(i.close) : ''}</span></div>`).join(''); box.classList.toggle('hidden', !r.items.length); }, 200); };
box.onclick = e => { const d = e.target.closest('div[data-code]'); if (d) { box.classList.add('hidden'); qs.value = ''; openStock(d.dataset.code); } };
qs.onkeydown = e => { if (e.key === 'Enter') { box.classList.add('hidden'); searchStock(qs.value.trim(), c => { qs.value = ''; openStock(c); }); } };
document.addEventListener('click', e => { if (!e.target.closest('.actions')) box.classList.add('hidden'); });
document.addEventListener('keydown', e => { if (e.key === '/' && !e.target.closest('input,textarea')) { e.preventDefault(); qs.focus(); } });

/* ---------- 表格排序 (點表頭：第一次由大到小，再點一次由小到大) ---------- */
function parseCell(td) {
  const t = (td.textContent || '').trim().replace(/,/g, '').replace(/即時/, '');
  if (t === '' || t === '-') return null;
  const m = t.match(/^([+-]?\d+(?:\.\d+)?)\s*(億|萬|%|x)?/);
  if (!m) return t.toLowerCase();
  let v = parseFloat(m[1]);
  if (m[2] === '億') v *= 1e8; else if (m[2] === '萬') v *= 1e4;
  return v;
}
document.body.addEventListener('click', e => {
  const th = e.target.closest('.tbl th'); if (!th) return;
  const table = th.closest('table'); const ths = [...th.parentElement.children]; const idx = ths.indexOf(th);
  const dir = th.dataset.dir === 'desc' ? 'asc' : th.dataset.dir === 'asc' ? 'none' : 'desc';  // 三段式: 降冪 → 升冪 → 取消
  ths.forEach(h => { h.dataset.dir = ''; h.classList.remove('sorted'); const a = h.querySelector('.arrow'); if (a) a.remove(); });
  const trs = [...table.querySelectorAll('tr')].slice(1);
  const groups = [];
  trs.forEach(tr => { if (tr.classList.contains('expand') && groups.length) groups[groups.length - 1].push(tr); else groups.push([tr]); });
  if (!table._orig || !table.contains(table._orig[0][0])) table._orig = groups.slice();  // 記住原始順序 (表格重繪後自動更新)
  if (dir === 'none') { table._orig.forEach(g => g.forEach(tr => table.appendChild(tr))); toast('已取消排序'); return; }
  th.dataset.dir = dir; th.classList.add('sorted');
  th.insertAdjacentHTML('beforeend', `<span class="arrow">${dir === 'desc' ? ' ▼' : ' ▲'}</span>`);
  const val = g => { const td = g[0].children[idx]; return td ? parseCell(td) : null; };
  groups.sort((a, b) => {
    const x = val(a), y = val(b);
    if (x === null && y === null) return 0; if (x === null) return 1; if (y === null) return -1;
    if (typeof x === 'number' && typeof y === 'number') return dir === 'desc' ? y - x : x - y;
    return dir === 'desc' ? String(y).localeCompare(String(x), 'zh-Hant') : String(x).localeCompare(String(y), 'zh-Hant');
  });
  groups.forEach(g => g.forEach(tr => table.appendChild(tr)));
});

/* ---------- 啟動 ---------- */
const loaders = { overview: loadOverview, news: loadNews, recommend: loadRecommend, technical: loadTechnical, chips: loadChips, rankings: loadRankings, watchlist: loadWatchlist, stock: () => { } };
try { applyTheme(localStorage.getItem('theme') || 'dark'); } catch (e) { applyTheme('dark'); }
if (STATIC) {
  document.body.classList.add('static');
  const wh = document.querySelector('#tab-watchlist .hint'); if (wh) wh.textContent = '雲端版：自選股存在這支手機/瀏覽器裡（換裝置不會同步）。顯示每日收盤資料；點列展開可編輯備註。';
  sjson('status.json').then(s => { const n = $('#cloudNote'); n.classList.remove('hidden'); n.textContent = `☁️ 雲端版 · 自動更新 ${s.built || ''}（新聞每 2 小時、行情每交易日 15:30 後）`; }).catch(() => { });
}
(async () => {
  try { const d = await api('/api/watchlist'); watchSet = new Set(d.items.map(i => i.code)); $('#wlCount').textContent = d.items.length || ''; liveTrading = d.trading; $('#liveBar').classList.toggle('hidden', !liveTrading); } catch (e) { }
  await loadFactors();
  pollStatus();
  const h = location.hash.replace('#', '');
  showTab(h && loaders[h] ? h : 'overview');
})();


/* ---------- 手機連線 / Modal ---------- */
function openModal(html) { $('#modalBody').innerHTML = html; $('#modal').classList.remove('hidden'); }
$('#modalClose').onclick = () => $('#modal').classList.add('hidden');
$('#modal').onclick = e => { if (e.target.id === 'modal') $('#modal').classList.add('hidden'); };
$('#btnMobile').onclick = async () => {
  const m = await api('/api/mobile?port=' + (location.port || 80));
  openModal(`<h2>📱 手機 / 平板 連線</h2>
    <p>手機與電腦連到<b>同一個 Wi-Fi</b>，用手機 Chrome 掃描下方 QR Code，或直接輸入：</p>
    <p class="url"><a href="${esc(m.url)}">${esc(m.url)}</a></p>
    <div class="qr">${m.svg}</div>
    <ol class="small">
      <li>電腦第一次使用：在 <span class="kbd">allow_firewall.bat</span> 按右鍵 →「以系統管理員身分執行」開放防火牆 (只需一次)。</li>
      <li>電腦要用 <span class="kbd">run.bat</span> 啟動並保持開啟，手機才連得到。</li>
      <li>手機 Chrome 開啟後，按右上「⋮」→「加到主畫面」，就會像 App 一樣有圖示可直接開啟。</li>
      <li>若連不上：確認防火牆已開放、兩邊同一 Wi-Fi、電腦 IP 未變更 (目前 ${esc(m.ip)})。</li>
    </ol>`);
};
document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#modal').classList.add('hidden'); });
