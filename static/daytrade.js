/* ⚡ 當沖雷達 (盤中每 5 秒) + 收盤後隔日沖券商判斷 */
const DT = { timer: null, closeTimer: null, open: new Set(), alerted: new Set(), lastItems: [], barsCache: {}, qT: null };
const dtMom = m => m.mom10 === null || m.mom10 === undefined ? '' : ` <span class="small" title="近 10 分鐘漲跌 ${m.mom10 > 0 ? '+' : ''}${m.mom10}%">${m.mom10 > 0.3 ? '↗' : m.mom10 < -0.3 ? '↘' : '→'}</span>`;
const dtDirBadge = m => m.direction === 'bull' ? `<span class="badge ${m.mom10 !== null && m.mom10 !== undefined && m.mom10 < -0.3 ? 'risk' : 'bull'}" title="多方條件 ${m.bull}/4：價漲、外盤≥55%、站上均價、近高點。方向描述的是「目前狀態」(落後指標)，箭頭是近 10 分鐘動能：偏多但 ↘ 代表正在轉弱，不追">偏多 ${m.bull}/4${m.mom10 !== null && m.mom10 !== undefined && m.mom10 < -0.3 ? '(轉弱)' : ''}</span>${dtMom(m)}` : m.direction === 'bear' ? `<span class="badge ${m.mom10 !== null && m.mom10 !== undefined && m.mom10 > 0.3 ? 'risk' : 'bear'}" title="空方條件 ${m.bear}/4：價跌、內盤≥55%、跌破均價、近低點。箭頭是近 10 分鐘動能：偏空但 ↗ 代表正在反彈，等反彈失敗再空">偏空 ${m.bear}/4${m.mom10 !== null && m.mom10 !== undefined && m.mom10 > 0.3 ? '(反彈)' : ''}</span>${dtMom(m)}` : `<span class="badge neu">震盪</span>${dtMom(m)}`;
const dtBar = (outer, inner) => { const t = outer + inner; if (!t) return '<span class="muted">累積中</span>'; const o = Math.round(outer / t * 100); return `<div class="iobar" title="外盤 ${fmt(outer, 0)} 張 / 內盤 ${fmt(inner, 0)} 張"><div class="o" style="width:${o}%"></div><div class="i" style="width:${100 - o}%"></div><span>${o}%</span></div>`; };
const dtSig = x => { const cls = /✘/.test(x) ? 'risk' : /✔|⚠/.test(x) ? (x.includes('✔') ? 'f' : 'risk') : /漲停|外盤強|站上均價|開高走高|開低走高|近高點|買盤掛單厚|爆量/.test(x) ? 'bull' : /跌停|內盤強|跌破均價|開高走低|開低走低|近低點|賣壓掛單重/.test(x) ? 'bear' : ''; return `<span class="badge ${cls}">${esc(x)}</span>`; };
const newsBadge = n => !n ? '' : `<span class="badge ${n.sent === 1 ? 'bull' : n.sent === -1 ? 'bear' : ''}" title="近 36 小時 ${n.n} 則新聞，最新：${esc(n.title || '')}${n.bull ? '　偏多 ' + n.bull : ''}${n.bear ? '　偏空 ' + n.bear : ''}">📰${n.n > 1 ? '×' + n.n : ''}</span>`;
const ydayBadge = y => !y ? '' : y.verdict === 'short' && !y.on_buy ? `<span class="badge bear" title="${y.date} 大跌收低、賣超集中的弱勢股，判斷今日反彈不過均價續空">昨判弱勢偏空</span>` : y.verdict === 'short' ? `<span class="badge bear" title="${y.date} 隔日沖券商買超 ${fmt(y.on_buy, 0)} 張 (${y.on_buy_pct}% 成交量)，今日開高留意出貨">昨隔日沖買超${fmt(y.on_buy, 0)}張</span>` : `<span class="badge bull" title="${y.date} 判斷隔日偏多 (隔日沖已出貨 ${fmt(y.on_sell, 0)} 張 / 主力非隔日沖)">昨判偏多</span>`;
const DT_SORT_ALT = { pct: 'pct_down', pct_down: 'pct', outer: 'inner', inner: 'outer' };
const DT_HEAD = `<tr><th>股票</th><th class="num" title="最新成交價 (約 5 秒延遲)">現價</th><th class="num" data-sort="pct" title="相對昨收的漲跌幅 (點一下漲幅排序、再點跌幅排序)">漲跌</th><th class="num" data-sort="amp" title="(今日最高 − 最低) ÷ 昨收，越大越適合當沖 (點表頭排序)">振幅</th><th class="num" title="開盤價相對昨收">跳空</th>
  <th class="num" data-sort="volume" title="今日累積成交張數 (點表頭排序)">成交(張)</th><th class="num" data-sort="vol_ratio" title="時間量比 = 累積量 ÷ (20日均量 × 已開盤時間比例) (點表頭排序)">時間量比</th><th class="num" data-sort="burst" title="最近 1 分鐘成交張數 (右邊小字 = 相對今日每分鐘平均量的倍數；點表頭依倍數排序)">1分量</th>
  <th data-sort="outer" title="外盤比 = 買方主動成交量 ÷ 已分類成交量。紅 = 外盤 (買方追價)、綠 = 內盤 (賣方殺出)。點一下外盤比排序、再點內盤比排序">外盤比 (紅買/綠賣)</th><th class="num" data-sort="net5" title="近 5 分鐘 外盤量 − 內盤量 (張)，正 = 買方站多 (點表頭排序)">5分淨買</th>
  <th class="num" title="現價相對當日成交量加權均價 (VWAP) 的百分比">vs均價</th><th class="num" data-sort="book" title="(五檔買量 − 五檔賣量) ÷ 總掛單量，正 = 買盤掛單厚 (點表頭排序)">掛單差</th><th title="多空方向：四個條件同時滿足三個以上">方向</th><th>訊號</th></tr>`;
function dtRow(r) {
  const o = DT.open.has(r.code);
  return `<tr class="row ${o ? 'open' : ''}" data-code="${r.code}"><td>${codeLink(r.code, r.name)}${star(r.code)}<div class="muted">${esc(r.market)} ${esc(r.industry)}</div></td>
    <td class="num"><b>${fmt(r.price)}</b></td><td class="num">${pct(r.pct)}</td><td class="num"><b>${fmt(r.amp, 1)}%</b></td><td class="num">${pct(r.gap)}</td>
    <td class="num">${fmt(r.volume, 0)}<div class="muted small">昨 ${fmt(r.prev_lots, 0)}</div></td><td class="num">${r.vol_ratio === null ? '-' : `<span class="${r.vol_ratio >= 2 ? 'up' : ''}">${fmt(r.vol_ratio, 1)}x</span>`}</td>
    <td class="num">${fmt(r.vol1, 0)}${r.burst ? `<span class="muted small"> ${fmt(r.burst, 1)}x</span>` : ''}</td><td>${dtBar(r.outer, r.inner)}</td><td class="num">${signed(r.net5)}</td>
    <td class="num">${r.vwap_pos === null ? '-' : pct(r.vwap_pos)}</td><td class="num">${r.book === null ? '-' : signed(r.book) + '%'}</td><td>${dtDirBadge(r)}</td>
    <td class="small">${ydayBadge(r.yday)}${newsBadge(r.news)}${(r.signals || []).map(dtSig).join('')}</td></tr>
    <tr class="expand dt-expand" data-code="${r.code}"><td colspan="14"><div class="dtx"><canvas class="dtchart" width="900" height="200" data-code="${r.code}"></canvas>
      <div class="dtxinfo" id="dtx-${r.code}"></div></div></td></tr>`;
}
function dtDrawChart(code, data) {
  const cv = document.querySelector(`canvas.dtchart[data-code="${code}"]`); if (!cv || !data || !data.bars || !data.bars.length) return;
  const W = cv.width = cv.parentElement.clientWidth || 900, H = cv.height = 200, ctx = cv.getContext('2d');
  const light = document.documentElement.dataset.theme === 'light';
  ctx.clearRect(0, 0, W, H);
  const bars = data.bars.slice(-270), n = bars.length, padL = 54, padR = 10, top = 8, ph = 118, vh = 54, vy = top + ph + 8;
  const w = (W - padL - padR) / Math.max(n, 60);
  let hi = Math.max(...bars.map(b => b.h)), lo = Math.min(...bars.map(b => b.l)); if (data.prev) { hi = Math.max(hi, data.prev); lo = Math.min(lo, data.prev); }
  if (hi === lo) { hi += 0.5; lo -= 0.5; }
  const y = p => top + (hi - p) / (hi - lo) * ph; const maxV = Math.max(1, ...bars.map(b => b.v));
  ctx.strokeStyle = light ? '#ccd3dc' : '#2a3441'; ctx.lineWidth = 1; ctx.font = '11px sans-serif'; ctx.fillStyle = light ? '#5b6878' : '#8b98a9'; ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) { const p = hi - (hi - lo) * i / 4, yy = y(p); ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke(); ctx.fillText(p.toFixed(p >= 500 ? 0 : p >= 50 ? 1 : 2), padL - 4, yy + 4); }
  if (data.prev) { ctx.setLineDash([4, 3]); ctx.strokeStyle = light ? '#9aa6b5' : '#55637a'; ctx.beginPath(); ctx.moveTo(padL, y(data.prev)); ctx.lineTo(W - padR, y(data.prev)); ctx.stroke(); ctx.setLineDash([]); }
  bars.forEach((b, i) => {
    const x = padL + i * w + w / 2, up = b.c >= b.o; ctx.strokeStyle = ctx.fillStyle = up ? UP : DN;
    ctx.beginPath(); ctx.moveTo(x, y(b.h)); ctx.lineTo(x, y(b.l)); ctx.stroke();
    const bw = Math.max(1.5, w * 0.7), yo = y(b.o), yc = y(b.c); ctx.fillRect(x - bw / 2, Math.min(yo, yc), bw, Math.max(1, Math.abs(yc - yo)));
    const tot = b.v || 0, scale = vh / maxV, hO = b.outer * scale, hI = b.inner * scale, hU = Math.max(0, (tot - b.outer - b.inner) * scale);
    let yb = vy + vh; ctx.fillStyle = UP; ctx.fillRect(x - bw / 2, yb - hO, bw, hO); yb -= hO; ctx.fillStyle = DN; ctx.fillRect(x - bw / 2, yb - hI, bw, hI); yb -= hI;
    if (hU > 0.5) { ctx.fillStyle = light ? '#b8c2cf' : '#55637a'; ctx.fillRect(x - bw / 2, yb - hU, bw, hU); }
  });
  let num = 0, den = 0, started = false; ctx.strokeStyle = '#f5a623'; ctx.lineWidth = 1.2; ctx.beginPath();
  bars.forEach((b, i) => { num += b.c * b.v; den += b.v; if (!den) return; const x = padL + i * w + w / 2, yy = y(num / den); if (!started) { ctx.moveTo(x, yy); started = true; } else ctx.lineTo(x, yy); });
  ctx.stroke();
  ctx.fillStyle = light ? '#5b6878' : '#8b98a9'; ctx.textAlign = 'left';
  bars.forEach((b, i) => { if (i % 30 === 0) ctx.fillText(b.t, padL + i * w, vy + vh + 12); });
  ctx.fillText(`${fmt(maxV, 0)}張/分`, padL + 2, vy + 10);
}
async function dtLoadBars(code) {
  try {
    const d = await api('/api/daytrade/bars/' + code); DT.barsCache[code] = d; dtDrawChart(code, d);
    const m = d.metrics || {}; const el = document.getElementById('dtx-' + code);
    if (el) el.innerHTML = `<b>${esc(d.name)}</b> 均價 ${fmt(d.vwap)} · 已分類量 外盤 <span class="up">${fmt(m.outer, 0)}</span> / 內盤 <span class="dn">${fmt(m.inner, 0)}</span> 張 (啟動前未分類 ${fmt(m.unclassified, 0)} 張) · 近 5 分淨買 ${signed(m.net5)} 張 · 預估全日量 ${fmt(m.est_day_lots, 0)} 張 · 區間位置 ${Math.round((m.pos || 0) * 100)}%
      <br><span class="muted">圖：1 分 K (紅漲綠跌)、橘線 = 累計均價 VWAP、虛線 = 昨收；下方量柱紅 = 外盤 (買方主動)、綠 = 內盤 (賣方主動)、灰 = 未分類。</span>`;
  } catch (e) { }
}
function dtCheckAlerts(items) {
  if (!$('#dtAlert').checked) return;
  const now = new Date().toLocaleTimeString('zh-TW', { hour12: false }).slice(0, 5);
  items.forEach(r => {
    const y = r.yday;
    if (y && y.verdict === 'short' && (r.signals || []).some(s => s.includes('昨空單:出貨中'))) {
      const key = r.code + ':Y'; if (!DT.alerted.has(key)) { DT.alerted.add(key); const msg = `${r.code} ${r.name} 昨日做空候選 → 已跌破均價/開盤價，內盤 ${100 - (r.outer_ratio || 50)}%，現價 ${r.price} (${r.pct > 0 ? '+' : ''}${r.pct}%)：出貨確認 ${now}`; toast(msg, 9000); try { if (Notification.permission === 'granted') new Notification('⚡ 當沖雷達 做空確認', { body: msg }); } catch (e) { } }
    }
    if (r.amp < 3 || (r.vol_ratio || 0) < 2 || r.outer_ratio === null || (r.outer + r.inner) < 300 || (r.outer_ratio < 60 && r.outer_ratio > 40)) return;
    const key = r.code + ':' + (r.outer_ratio >= 60 ? 'B' : 'S'); if (DT.alerted.has(key)) return; DT.alerted.add(key);
    const msg = `${r.code} ${r.name} ${r.outer_ratio >= 60 ? '🔴 買方站多' : '🟢 賣方站多'} 外盤比 ${r.outer_ratio}%，振幅 ${r.amp}%，時間量比 ${r.vol_ratio}x，現價 ${r.price} (${r.pct > 0 ? '+' : ''}${r.pct}%) ${now}`;
    toast(msg, 9000);
    try { if (Notification.permission === 'granted') new Notification('⚡ 當沖雷達', { body: msg }); else if (Notification.permission !== 'denied') Notification.requestPermission(); } catch (e) { }
  });
}
async function loadDaytrade() {
  if (STATIC) { $('#dtMeta').textContent = '雲端版不提供盤中雷達 (需本機 run.bat 伺服器)'; $('#dtTable').innerHTML = ''; loadDaytradeClose(); return; }
  try {
    const d = await api(`/api/daytrade/live?limit=${$('#dtLimit').value}&sort=${$('#dtSort').value}&direction=${$('#dtDir').value}&min_lots=${$('#dtMinLots').value}&q=${encodeURIComponent($('#dtQ').value.trim())}`);
    DT.lastItems = d.items;
    const fu = d.futures || {}; const fn = fu.night, fd = fu.day;
    const futTxt = (fn || fd) ? ` · 期貨${fn && fn.pct !== null && fn.pct !== undefined ? ` 夜盤 ${signed(fn.pct, 2)}%` : ''}${fd && fd.open_pct !== null && fd.open_pct !== undefined ? ` 日盤開 ${signed(fd.open_pct, 2)}% 現 ${signed(fd.pct, 2)}%` : ''}${fd && fd.open_pct !== null && fd.open_pct !== undefined ? (fd.open_pct < -0.3 ? ' ⚠ 期貨開低，昨空單今天不做' : fd.open_pct > 1 ? ' ✅ 期貨開高 >1%，昨空單勝率最高 (回測 86%)' : '') : ''}` : '';
    const mk = d.market; const mkTxt = mk ? ` · 大盤 ${signed(mk.pct, 2)}% (開盤 ${mk.open_pct === null ? '?' : signed(mk.open_pct, 2)}%)${mk.open_pct !== null && mk.open_pct < -0.3 ? ' ⚠ 大盤開低，昨空單今天不做' : mk.pct > 0 && mk.open_pct !== null && mk.pct > mk.open_pct + 0.3 ? ' ⚠ 大盤盤中轉強，空單縮手' : ''}` : '';
    $('#dtMeta').textContent = d.pool ? `掃描 ${d.pool} 檔 · 成交≥${fmt(d.min_lots, 0)}張且符合 ${d.total} 檔 · 顯示 ${d.items.length} 檔 · 開盤進度 ${d.session_pct}%${mkTxt}${futTxt}` : `尚未建立掃描池 (開盤 08:57 自動啟動)${futTxt}`;
    $('#dtTick').innerHTML = d.trading ? `<span class="live">LIVE</span> 每 ${d.poll_sec} 秒更新 · 最後 ${d.last_poll || '-'}` : d.last_poll ? `⏸ 非交易時間 · 顯示 ${d.date || ''} 盤中最後狀態 (${d.last_poll})` : '⏸ 非交易時間 · 今日尚無盤中資料';
    const tbl = $('#dtTable');
    if (!d.items.length) tbl.innerHTML = `<tr><td class="muted" style="padding:16px">${d.trading ? '資料累積中，請稍候幾秒…' : '目前沒有盤中資料。開盤後 (09:00) 這裡會每 5 秒更新；收盤後請看下方「隔日沖券商判斷」。'}</td></tr>`;
    else {
      tbl.innerHTML = DT_HEAD + d.items.map(dtRow).join('');
      // 標示目前的後端排序欄位；若使用者用表頭做了前端排序 (現價/跳空等無後端鍵的欄位)，刷新後重新套用
      const cur = $('#dtSort').value; const th = tbl.querySelector(`th[data-sort="${cur}"]`) || tbl.querySelector(`th[data-sort="${DT_SORT_ALT[cur] || ''}"]`);
      if (th) { th.classList.add('sorted'); th.insertAdjacentHTML('beforeend', `<span class="arrow"> ${cur === 'pct_down' || cur === 'inner' ? '▲' : '▼'}</span>`); }
      if (tbl._sortKeys && tbl._sortKeys.length && typeof applySort === 'function') { tbl._orig = null; applySort(tbl); }
      document.querySelectorAll('#dtTable tr.row').forEach(tr => tr.onclick = e => { if (e.target.closest('.code,.star,a,input,button')) return; const c = tr.dataset.code; tr.classList.toggle('open'); if (tr.classList.contains('open')) { DT.open.add(c); dtLoadBars(c); } else DT.open.delete(c); });
      DT.open.forEach(c => { if (d.items.some(r => r.code === c)) dtLoadBars(c); });
    }
    dtCheckAlerts(d.items);
    clearTimeout(DT.timer); DT.timer = setTimeout(() => { if (document.querySelector('#tab-daytrade').classList.contains('active')) loadDaytrade(); }, d.trading ? 5000 : 30000);
  } catch (e) { $('#dtMeta').textContent = '讀取失敗：' + e.message; clearTimeout(DT.timer); DT.timer = setTimeout(loadDaytrade, 10000); }
  if (!loadDaytrade.closeDone) { loadDaytrade.closeDone = true; loadDaytradeClose(); }
}
['#dtSort', '#dtDir', '#dtLimit', '#dtMinLots'].forEach(s => $(s).onchange = () => { try { localStorage.setItem('dtMinLots', $('#dtMinLots').value); localStorage.setItem('dtSort', $('#dtSort').value); } catch (e) { } loadDaytrade(); });
try { const v = localStorage.getItem('dtSort'); if (v && [...$('#dtSort').options].some(o => o.value === v)) $('#dtSort').value = v; } catch (e) { }
// 點表頭 = 切換後端排序 (在 #dtTable 上攔截，不走 app.js 的前端排序；沒有 data-sort 的欄位仍用前端排序)
$('#dtTable').addEventListener('click', e => {
  const th = e.target.closest('th[data-sort]'); if (!th) return;
  e.stopPropagation();
  const key = th.dataset.sort, cur = $('#dtSort').value;
  const next = cur === key && DT_SORT_ALT[key] ? DT_SORT_ALT[key] : key;
  $('#dtSort').value = next; $('#dtTable')._sortKeys = [];
  try { localStorage.setItem('dtSort', next); } catch (e2) { }
  toast(`排序：${$('#dtSort').selectedOptions[0].textContent}`);
  loadDaytrade();
});
try { const v = localStorage.getItem('dtMinLots'); if (v !== null) $('#dtMinLots').value = v; } catch (e) { }
$('#dtQ').oninput = () => { clearTimeout(DT.qT); DT.qT = setTimeout(loadDaytrade, 300); };
$('#dtAlert').onchange = () => { try { localStorage.setItem('dtAlert', $('#dtAlert').checked ? '1' : ''); } catch (e) { } if ($('#dtAlert').checked) { try { Notification.requestPermission(); } catch (e) { } } };
try { $('#dtAlert').checked = localStorage.getItem('dtAlert') === '1'; } catch (e) { }

/* ----- 收盤後: 隔日沖券商判斷 ----- */
const brokerList = (lst, sign) => (lst || []).slice(0, 5).map(b => `<span class="badge ${b.overnight ? (sign > 0 ? 'bear' : 'bull') : ''}" title="${b.overnight ? '隔日沖券商分點' : ''}${b.pct !== null && b.pct !== undefined ? ' 占成交 ' + b.pct + '%' : ''}">${esc(b.broker)} ${sign > 0 ? '+' : ''}${fmt(b.net, 0)}${b.overnight ? ' ⚡' : ''}</span>`).join('');
function dtCloseRow(x, kind) {
  return `<tr class="row" data-code="${x.code}"><td>${codeLink(x.code, x.name)}${star(x.code)}<div class="muted">${esc(x.market)} ${esc(x.industry)}</div></td>
    <td class="num">${fmt(x.close)}</td><td class="num">${pct(x.chg)}</td><td class="num">${fmt(x.amp, 1)}%</td><td class="num">${fmt(x.lots, 0)}<div class="muted small">${x.vol_ratio ? fmt(x.vol_ratio, 1) + 'x' : ''}</div></td>
    <td class="num">${x.dt_ratio === null || x.dt_ratio === undefined ? '-' : fmt(x.dt_ratio, 0) + '%'}</td>
    <td class="num">${kind === 'short' ? (x.chg < 0 ? `<span class="dn">−${fmt(x.on_sell, 0)}</span><div class="muted small">賣超 ${x.on_sell_pct}% · 前5集中 ${x.sell5_pct ?? '-'}%</div>` : `<span class="dn">+${fmt(x.on_buy, 0)}</span><div class="muted small">${x.on_buy_pct}%</div>`) : `<span class="up">−${fmt(x.on_sell, 0)}</span><div class="muted small">${x.on_sell_pct}%${x.on_buy ? ' / 買' + fmt(x.on_buy, 0) : ''}</div>`}</td>
    <td class="num"><span class="score ${x.score >= 60 ? 'hi' : x.score >= 35 ? 'mid' : ''}">${Math.round(x.score)}</span></td>
    <td class="small">${kind === 'short' && x.chg < 0 ? brokerList((x.sellers || []).slice(0, 3), -1) : brokerList((x.buyers || []).slice(0, 3), 1)}</td></tr>
    <tr class="expand"><td colspan="9">${x.news_n ? `<b>📰 當日新聞 ${x.news_n} 則：</b>${esc(x.news_title || '')}<br>` : ''}<b>判斷理由：</b>${(x.reasons || []).map(r => `<span class="badge ${kind === 'short' ? 'bear' : 'bull'}">${esc(r)}</span>`).join(' ')}
      ${x.risks && x.risks.length ? `<br><b>風險：</b>${x.risks.map(r => `<span class="badge risk">${esc(r)}</span>`).join(' ')}` : ''}
      <br><span class="muted">買超前 5：</span>${brokerList(x.buyers, 1)}<br><span class="muted">賣超前 5：</span>${brokerList(x.sellers, -1)}
      <br><span class="muted">開 ${fmt(x.open)} 高 ${fmt(x.high)} 低 ${fmt(x.low)} 收 ${fmt(x.close)} · 收在區間 ${Math.round((x.pos || 0) * 100)}% 位置 · 買超前 5 集中度 ${x.buy5_pct}% · 隔日沖分點買 ${fmt(x.on_buy, 0)} / 賣 ${fmt(x.on_sell, 0)} 張${x.dt_flag ? ' · ⚠ 證交所註記暫停先賣後買當沖' : ''}</span></td></tr>`;
}
const DT_CLOSE_HEAD = kind => `<tr><th>股票</th><th class="num">收盤</th><th class="num">漲跌</th><th class="num" title="當日振幅">振幅</th><th class="num" title="成交張數 / 量比">成交(張)</th><th class="num" title="當日沖銷成交量 ÷ 總成交量 (證交所/櫃買統計)">當沖比</th>
  <th class="num" title="${kind === 'short' ? '隔日沖券商分點合計買超張數 / 占成交量比例' : '隔日沖券商分點合計賣超張數 / 占成交量比例'}">${kind === 'short' ? '隔日沖買超' : '隔日沖賣超'}</th><th class="num" title="判斷強度">分數</th><th>${kind === 'short' ? '主要分點 (大漲=買超前 3 / 大跌=賣超前 3；⚡ = 隔日沖)' : '買超前 3 分點 (⚡ = 隔日沖)'}</th></tr>`;
async function loadDaytradeClose() {
  try {
    const d = await api('/api/daytrade/close'); const rep = d.report || {}, st = d.status || {};
    $('#dtCloseMeta').textContent = rep.date ? `分析日 ${rep.date}${rep.market_pct !== undefined && rep.market_pct !== null ? ` (大盤 ${rep.market_pct > 0 ? '+' : ''}${rep.market_pct}%)` : ''} · 候選 ${rep.n_candidates} 檔 · 計算於 ${rep.built}${rep.market_pct !== undefined && rep.market_pct !== null && rep.market_pct <= -2 ? ' · ⚠ 大盤重挫日，弱勢股隔日易反彈，做空 B 已改列觀察' : ''}` : '尚無資料';
    let status = '';
    if (st.running) status = `⏳ ${st.step} ${st.total ? `(${st.progress}/${st.total})` : ''}`;
    else if (st.error) status = '❌ ' + st.error;
    else if (d.target_date && rep.date !== d.target_date) status = `最新行情日 ${d.target_date} 的分點資料${st.step && st.step.includes('尚未公布') ? '尚未公布 (通常 16:00～18:00)，會自動重試' : '尚未分析，請按「重新計算」'}`;
    if (rep.summary) { const s = rep.summary; status += ` · 市場當沖比重：上市 ${s.twse ? s.twse.share_pct + '%' : '-'} / 上櫃 ${s.tpex ? s.tpex.share_pct + '%' : '-'}`; }
    $('#dtCloseStatus').textContent = status;
    $('#dtCloseRebuild').disabled = !!st.running;
    const empty = () => `<tr><td class="muted" style="padding:12px">${rep.date ? '沒有符合條件的股票' : '尚未計算'}</td></tr>`;
    $('#dtLong').innerHTML = (rep.long || []).length ? DT_CLOSE_HEAD('long') + rep.long.map(x => dtCloseRow(x, 'long')).join('') : empty();
    $('#dtShort').innerHTML = (rep.short || []).length ? DT_CLOSE_HEAD('short') + rep.short.map(x => dtCloseRow(x, 'short')).join('') : empty();
    $('#dtWatch').innerHTML = (rep.watch || []).length ? DT_CLOSE_HEAD('short') + rep.watch.map(x => dtCloseRow(x, x.on_buy_pct >= x.on_sell_pct ? 'short' : 'long')).join('') : empty();
    bindExpand('#dtLong'); bindExpand('#dtShort'); bindExpand('#dtWatch');
    if (!loadDaytradeClose.verifyAt || Date.now() - loadDaytradeClose.verifyAt > 120000) { loadDaytradeClose.verifyAt = Date.now(); loadDaytradeVerify(); }
    clearTimeout(DT.closeTimer); DT.closeTimer = setTimeout(() => { if (document.querySelector('#tab-daytrade').classList.contains('active')) loadDaytradeClose(); }, st.running ? 3000 : 60000);
  } catch (e) { $('#dtCloseStatus').textContent = '讀取失敗：' + e.message; }
}
async function loadDaytradeVerify() {
  try {
    const d = await api('/api/daytrade/verify?days=20'); const s = d.summary || {};
    const tile = (label, v, cls) => !v ? '' : `<div class="tile"><div class="n">${label}</div><div class="v ${cls}">${v.win}% <span class="muted small">(${v.hit}/${v.n})</span></div><div class="p">開→收 平均 ${signed(v.avg_move, 2)}% · 最佳 ${fmt(v.avg_best, 1)}%</div></div>`;
    $('#dtVerifySummary').innerHTML = tile('🟢 做空候選 命中率 (全部名單)', s.short, 'dn') + tile('✅ 其中符合執行條件 (隔日開高 0～3%)', s.short_exec, 'dn') + tile('🚀 執行條件 + 期貨 08:45 開高 >1%', s.short_exec_futup, 'dn') + tile('🔴 做多候選 命中率', s.long, 'up');
    const days = d.days || [];
    $('#dtVerifyMeta').textContent = days.length ? `已驗證 ${days.filter(x => x.next).length} 天名單` : '尚無可驗證的名單 (收盤後產生名單、隔天開盤後自動對照)';
    const rows = [];
    days.forEach(day => {
      if (!day.next) { rows.push(`<tr><td colspan="9" class="muted">${day.date} 名單：${day.note}</td></tr>`); return; }
      const mk = v => v === null || v === undefined ? '?' : `${v > 0 ? '+' : ''}${v}%`;
      rows.push(`<tr><td colspan="9" style="background:var(--card2)"><b>${day.date} 名單 → ${day.next} ${day.src}</b>　做空命中 ${day.short_hit}/${day.short_n}　做多命中 ${day.long_hit}/${day.long_n}　<span class="muted" title="名單日大盤漲跌 → 隔日大盤漲跌。做空名單在隔日大盤下跌時命中率高、大盤反彈日明顯失效，開盤先看大盤方向">大盤 ${mk(day.market_pct)} → 隔日 ${mk(day.next_market_pct)}　期貨夜盤 ${mk(day.fut_night_pct)} → 隔日期貨開盤 ${mk(day.fut_open_pct)}</span></td></tr>`);
      day.items.sort((a, b) => (a.verdict === b.verdict ? b.score - a.score : a.verdict === 'short' ? -1 : 1)).forEach(i => rows.push(`<tr class="row"><td>${codeLink(i.code, i.name)}</td><td><span class="badge ${i.verdict === 'short' ? 'bear' : 'bull'}">${i.verdict === 'short' ? (i.rule === 'short_a' ? '做空A 隔日沖' : '做空B 弱勢') : '做多'}</span></td>
        <td class="num">${Math.round(i.score)}</td><td class="num">${fmt(i.prev_close)}</td><td class="num">${pct(i.gap)}</td><td class="num"><b>${pct(i.move)}</b></td><td class="num">${pct(i.chg)}</td><td class="num">${fmt(i.best, 1)}%</td><td>${i.hit ? '<span class="badge bull">✔ 命中</span>' : '<span class="badge risk">✘ 未命中</span>'} <span class="muted small">${esc(i.reason.slice(0, 28))}</span></td></tr>`));
    });
    $('#dtVerifyTable').innerHTML = `<tr><th>股票</th><th>類型</th><th class="num">分數</th><th class="num">名單日收盤</th><th class="num" title="隔日開盤相對名單日收盤">跳空</th><th class="num" title="隔日 開盤→收盤 (盤中為現價)">開→收</th><th class="num" title="隔日收盤相對名單日收盤">漲跌</th><th class="num" title="開盤後順向最大幅度">最佳</th><th>結果</th></tr>` + rows.join('');
  } catch (e) { $('#dtVerifyMeta').textContent = '讀取失敗：' + e.message; }
}
$('#dtCloseRebuild').onclick = async () => { const r = await api('/api/daytrade/close?force=1', { method: 'POST' }); if (!STATIC) { toast(r.started ? '開始抓券商分點並重新判斷 (約 1～2 分鐘)' : '目前正在計算中'); setTimeout(loadDaytradeClose, 1500); } };
loaders.daytrade = loadDaytrade;
