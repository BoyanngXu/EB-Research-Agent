/* EB 投研 Agent 平台 —— 前端逻辑（原生 JS，无框架） */
'use strict';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

let CFG = null;
let ES = null;              // 当前 SSE 连接
let txtFiles = [];          // Anno 已转储文本
let selectedTxt = new Set();

// ------------------------------------------------------------------ 基础
async function api(url, opts) {
  const r = await fetch(url, opts);
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('json')) return r.json();
  return { ok: r.ok, text: await r.text() };
}
const get = (u) => api(u);
const post = (u, b) => api(u, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(b || {})
});

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function fmtSize(n) {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0; n = Number(n);
  while (n >= 1024 && i < 3) { n /= 1024; i++; }
  return (i === 0 ? n.toFixed(0) : n.toFixed(1)) + ' ' + u[i];
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN', { hour12: false });
}

// ------------------------------------------------------------------ Tab
let CURRENT_TAB = 'assistant';
function showTab(page) {
  $$('.tab').forEach(x => x.classList.remove('active'));
  $$('.page').forEach(x => x.classList.remove('active'));
  const t = $$('.tab[data-page="' + page + '"]')[0];
  if (t) t.classList.add('active');
  const pg = $('#page-' + page); if (pg) pg.classList.add('active');
  CURRENT_TAB = page;
  if (page === 'assistant') { initAssistant(); }
  if (page === 'data') loadDataDates();
  if (page === 'anno') { loadTxt(); autoWatchAnno(); }
  if (page === 'wechat') loadWechat();
  if (page === 'report') loadReport();
  if (page === 'overview-settings') { loadOverview(); loadSettings(); }
}
$$('.tab').forEach(t => t.onclick = () => showTab(t.dataset.page));

// ------------------------------------------------------------------ 日志
function logTo(el, text, level) {
  el = typeof el === 'string' ? $(el) : el;
  if (el.textContent) el.textContent += '\n';
  el.textContent += text;
  el.scrollTop = el.scrollHeight;
}

function appendLog(el, rec) {
  el = typeof el === 'string' ? $(el) : el;
  if (!el) return;
  const line = document.createElement('div');
  line.className = 'l-' + ((rec && rec.level) || 'info');
  line.textContent = rec.text;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

/** 用快照整体重绘日志区（过滤掉结构化进度，避免重复追加）。 */
function renderTaskLog(el, t) {
  if (!el) return;
  const logs = (t.log || []).filter(r => r && r.level !== 'progress');
  el.innerHTML = '';
  logs.forEach(r => appendLog(el, r));
}

/** 订阅任务日志；done 回调收到最终 task snapshot（含 result）。
 *
 * 优先用 SSE（EventSource）实时推；一旦 SSE 连接失败（被代理缓冲、混合内容拦截、
 * 或浏览器对未分帧的 HTTP/1.1 流不触发事件等），自动降级为轮询
 * GET /api/tasks/<tid>，保证「执行日志 + 进度条」始终可见。
 */
function watchTask(tid, logEl, onDone, opts) {
  opts = opts || {};
  const drivesProgress = !!opts.progress;
  const el = typeof logEl === 'string' ? $(logEl) : logEl;

  let finished = false;
  const done = (t) => {
    if (finished) return;
    finished = true;
    stopPoll();
    if (ES) { try { ES.close(); } catch (e) {} ES = null; }
    if (drivesProgress) hideProgressPanel();
    if (onDone) onDone(t);
  };

  // 轮询兜底 + 立即可见：不依赖 SSE 是否真能把事件送进浏览器。
  // 右栏/代理下 SSE 常见「连上了但被缓冲、onerror 永不触发」，旧逻辑只在 onerror
  // 时才启动轮询，导致日志一直空。改为：立刻拉一次快照 + 每秒轮询，保证日志/进度始终可见。
  let pollTimer = null;
  const stopPoll = () => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } };
  const tick = async () => {
    try {
      const r = await get('/api/tasks/' + tid);
      if (!r || !r.ok || !r.task) return;
      renderTaskLog(el, r.task);
      if (drivesProgress && r.task.progress) updateProgressPanel(JSON.stringify(r.task.progress));
      if (['done', 'failed', 'stopped'].includes(r.task.status)) done(r.task);
    } catch (e) { /* 单次轮询失败忽略 */ }
  };
  const startPoll = () => { if (pollTimer || finished) return; tick(); pollTimer = setInterval(tick, 1000); };
  startPoll();   // 立即渲染历史日志 + 之后每秒刷新，彻底摆脱对 SSE 送达的依赖

  // SSE 仅作实时增强：能在浏览器里送达时进度更跟手；完成信号走 status/end。
  // 日志统一由轮询整体重绘（renderTaskLog 会清空再重建），避免与 SSE 增量 append 重复/闪烁。
  if (ES) { try { ES.close(); } catch (e) {} ES = null; }
  const es = new EventSource('/api/tasks/' + tid + '/stream');
  ES = es;
  es.addEventListener('snapshot', () => { /* 由轮询兜底渲染，避免与轮询重复 */ });
  es.addEventListener('log', (e) => {
    try {
      const rec = JSON.parse(e.data);
      if (rec.level === 'progress' && drivesProgress) updateProgressPanel(rec.text);
    } catch (_) {}
  });
  es.addEventListener('status', (e) => { try { const t = JSON.parse(e.data); done(t); } catch (_) {} });
  es.addEventListener('end', () => { done(null); });
  // 不主动关 SSE：轮询已兜底渲染，SSE 若能送达则进度更实时，断了浏览器也会自动重连。
  es.onerror = () => {};
  return es;
}

/** 渲染「执行进度」面板（来自任务 stream 的 level='progress' 记录）。 */
function updateProgressPanel(text) {
  try {
    const p = JSON.parse(text);
    $('#annoProgressCard').style.display = '';
    $('#ppPhase').textContent = p.phase || '-';
    $('#ppFileTxt').textContent = `文件 ${p.done || 0}/${p.total || 0}`;
    $('#ppFileName').textContent = p.name || '';
    $('#ppFileBar').style.width = (p.total > 0 ? (p.done / p.total * 100) : 0) + '%';
  } catch (e) { /* 解析失败忽略 */ }
}

/** 收起「执行进度」面板（任务结束或切到非分析任务时调用）。 */
function hideProgressPanel() {
  const card = $('#annoProgressCard');
  if (card) card.style.display = 'none';
}

// ------------------------------------------------------------------ 自动挂载正在运行的任务
// 让「主页面（含右栏/侧栏打开的同一页面）」在打开时即自动显示进度条+日志，
// 不必非得从这一页点「开始精读」才订阅任务。（修复：后台/API 启动的任务在前端不可见）
let _watchedTid = null;
function watchAnnoTask(tid) {
  if (!tid || tid === _watchedTid) return;
  _watchedTid = tid;
  watchTask(tid, '#annoLog', () => { _watchedTid = null; loadBridge(); }, { progress: true });
}
async function autoWatchAnno() {
  // 用户在对话助手页聊天时，不强行切回公告页挂载进度
  if (CURRENT_TAB === 'assistant') return;
  // 已在 watch 中且任务仍在进行 -> 不重复挂载
  if (_watchedTid) {
    try {
      const cur = await get('/api/tasks/' + _watchedTid);
      if (cur && cur.task && ['done', 'failed', 'stopped'].includes(cur.task.status)) {
        _watchedTid = null;
      } else {
        return;
      }
    } catch (e) { _watchedTid = null; }
  }
  try {
    const r = await get('/api/tasks?limit=10');
    const tasks = (r && r.tasks) || [];
    tasks.sort((a, b) => (b.started || 0) - (a.started || 0));
    const t = tasks.find(x => x.project === 'anno' && /精读/.test(x.title || '')
                          && ['running', 'pending'].includes(x.status));
    if (t) {
      if (CURRENT_TAB !== 'anno') showTab('anno');   // 自动切到公告页，确保进度条可见
      watchAnnoTask(t.id);
    }
  } catch (e) {}
}

/** 起任务 → 挂日志 → 回调。统一处理按钮禁用。 */
async function runTask(btn, url, body, logEl, onDone, opts) {
  const el = typeof logEl === 'string' ? $(logEl) : logEl;
  if (btn) btn.disabled = true;
  el.textContent = '';
  try {
    const res = await post(url, body);
    if (!res.ok) {
      appendLog(el, { text: '启动失败：' + (res.error || '未知错误'), level: 'error' });
      if (btn) btn.disabled = false;
      return null;
    }
    watchTask(res.task.id, el, (t) => {
      if (btn) btn.disabled = false;
      if (onDone) onDone(t);
    }, opts);
    return res.task;
  } catch (e) {
    appendLog(el, { text: '请求异常：' + e.message, level: 'error' });
    if (btn) btn.disabled = false;
    return null;
  }
}

// ------------------------------------------------------------------ 文件预览
async function previewFile(path, container) {
  const el = typeof container === 'string' ? $(container) : container;
  el.innerHTML = '<div class="empty">加载中…</div>';
  const r = await get('/api/file/preview?path=' + encodeURIComponent(path));
  if (!r.ok) {
    el.innerHTML = `<div class="note err">预览失败：${esc(r.error)}</div>`;
    return;
  }
  if (r.rows !== undefined) {          // xlsx
    el.innerHTML = renderTable(r);
  } else if (r.paragraphs !== undefined) {  // docx
    el.innerHTML = `<div class="card"><h3>${esc(r.title)}</h3>
      <p class="desc">${esc(r.author || '')} · 共 ${r.chars} 字</p>
      ${r.paragraphs.map(p => `<p style="text-indent:2em;margin:6px 0">${esc(p)}</p>`).join('')}</div>`;
  } else if (r.text !== undefined) {   // pdf / txt
    el.innerHTML = `<div class="card"><h3>${esc(path.split(/[\\/]/).pop())}</h3>
      ${r.pages ? `<p class="desc">共 ${r.total_pages || r.pages} 页${r.scanned ? ' · <b style="color:var(--warn)">疑似扫描件（无文字层）</b>' : ''}</p>` : ''}
      <div class="log" style="max-height:420px">${esc(r.text.slice(0, 20000))}</div></div>`;
  } else {
    el.innerHTML = '<div class="empty">不支持预览</div>';
  }
}

function renderTable(r) {
  // 表头含涨跌/同比的列，按中国习惯：正红负绿
  const isDelta = (h) => /涨跌|同比|环比|增幅|变化/.test(String(h || ''));
  const head = (r.headers || []).map(h => `<th>${esc(h)}</th>`).join('');
  const body = (r.rows || []).map(row => '<tr>' + row.map((c, i) => {
    let cls = '';
    if (isDelta((r.headers || [])[i])) {
      const n = parseFloat(String(c).replace(/[%,]/g, ''));
      if (!isNaN(n)) cls = n > 0 ? ' class="up"' : (n < 0 ? ' class="down"' : '');
    }
    return `<td${cls}>${esc(c)}</td>`;
  }).join('') + '</tr>').join('');
  return `<div class="toolbar"><span class="faint">${r.sheets.length} 个工作表 · 当前「${esc(r.sheet)}」· ${r.rows.length} 行${r.truncated ? '（已截断）' : ''}</span></div>
    <div class="tablewrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderFileList(container, files, onPick, opts) {
  const el = typeof container === 'string' ? $(container) : container;
  opts = opts || {};
  if (!files || !files.length) {
    el.innerHTML = '<div class="empty">' + (opts.empty || '暂无文件') + '</div>';
    return;
  }
  el.innerHTML = files.map((f, i) => `
    <div class="item" data-i="${i}">
      ${opts.checkbox ? `<input type="checkbox" class="fchk" data-i="${i}">` : ''}
      <span class="name">${esc(f.name)}</span>
      ${f.scanned ? `<span class="tag scan" title="${esc((f.images||[]).join('\n'))}">扫描件·已渲染${f.pages||0}页</span>` : ''}
      <span class="meta">${fmtSize(f.size)} · ${fmtTime(f.mtime)}</span>
      ${f.scanned && f.pages_dir ? `<button class="btn-sm" data-open="${esc(f.pages_dir)}">看图</button>` : ''}
    </div>`).join('');
  el.querySelectorAll('.item').forEach(it => {
    it.onclick = (e) => {
      if (e.target.classList.contains('fchk')) return;
      if (e.target.closest('[data-open]')) return;
      onPick && onPick(files[+it.dataset.i]);
    };
  });
  el.querySelectorAll('[data-open]').forEach(btn => {
    btn.onclick = (e) => { e.stopPropagation(); openPath(btn.dataset.open); };
  });
  if (opts.checkbox) {
    el.querySelectorAll('.fchk').forEach(cb => {
      cb.onchange = () => {
        const f = files[+cb.dataset.i];
        if (cb.checked) opts.onCheck(f); else opts.onUncheck(f);
      };
    });
  }
}

async function openPath(path) { await post('/api/file/open', { path }); }

// ------------------------------------------------------------------ 设置
async function loadOverview() {
  const [dates, txt, wc, env] = await Promise.all([
    get('/api/data/dates'), get('/api/anno/txt'), get('/api/wechat/articles'), get('/api/env')
  ]);
  $('#ovDataCount').textContent = (dates.dates || []).length;
  $('#ovAnnoCount').textContent = (txt.files || []).length;
  $('#ovWcCount').textContent = (wc.files || []).length;
  const deps = env.deps || [];
  const missing = deps.filter(d => !d.installed);
  $('#ovDepCount').textContent = `${deps.length - missing.length}/${deps.length}`;

  const notes = [];
  if (missing.filter(d => d.required).length) {
    notes.push(`<div class="note warn"><b>缺少必需依赖</b>：${missing.filter(d => d.required).map(d => d.pip).join('、')} —— 去「设置 → 运行环境」一键安装。</div>`);
  }
  notes.push(`<div class="note">当前解释器：<span class="mono">${esc(env.python.executable)}</span>（Python ${esc(env.python.version)}）</div>`);
  $('#ovNote').innerHTML = notes.join('');
  $('#envLine').textContent = `Python ${env.python.version} · ${deps.length - missing.length}/${deps.length} 依赖`;

  const ts = await get('/api/tasks?limit=8');
  const list = ts.tasks || [];
  $('#ovTasks').innerHTML = list.length ? list.map(t => `
    <div class="item"><span class="dot ${t.status === 'done' ? 'ok' : (t.status === 'failed' ? 'err' : (t.status === 'running' ? 'warn' : ''))}"></span>
      <span class="name">${esc(t.title)}</span>
      <span class="badge">${esc(t.project || '-')}</span>
      <span class="meta">${esc(t.status)}</span></div>`).join('')
    : '<div class="empty">暂无任务</div>';
}

// ------------------------------------------------------------------ 数据
async function loadDataDates() {
  const r = await get('/api/data/dates?dir=' + encodeURIComponent($('#dataDir').value || ''));
  if (!r.ok) return;
  const sel = $('#dataDate');
  const cur = sel.value;
  sel.innerHTML = (r.dates || []).map(d => `<option value="${esc(d.name)}">${esc(d.name)}</option>`).join('')
    || '<option value="">（无日期目录）</option>';
  if (cur && (r.dates || []).some(d => d.name === cur)) sel.value = cur;
  await loadSources();
}

async function loadSources() {
  const d = $('#dataDate').value;
  if (!d) { $('#srcStatus').innerHTML = ''; return; }
  const r = await get('/api/data/sources?date=' + encodeURIComponent(d)
    + '&dir=' + encodeURIComponent($('#dataDir').value || ''));
  if (!r.ok) return;
  const items = (r.sources || []).map(s => `
    <div class="item"><span class="badge ${s.exists ? 'ok' : 'err'}">${s.exists ? '齐' : '缺'}</span>
      <span class="name">${esc(s.name)}</span>
      <span class="meta">${s.exists ? fmtSize(s.size) : '未找到'}</span></div>`).join('');
  $('#srcStatus').innerHTML =
    (r.ready ? '<div class="note ok">四份源文件齐全，可以重建。</div>'
      : '<div class="note warn">源文件不齐，缺的请先到上面下载，或手动放进该目录。</div>')
    + `<div class="filelist">${items}</div>`;
}

$('#dataDir').addEventListener('change', loadDataDates);
$('#dataDate').addEventListener('change', loadSources);
$('#btnRefreshDates').onclick = loadDataDates;

$('#btnXx').onclick = () => runTask($('#btnXx'), '/api/data/download-xx',
  { dir: $('#dataDir').value },
  '#dataLog', () => { loadDataDates(); listDataOut(); });
$('#btnSz').onclick = () => runTask($('#btnSz'), '/api/data/download-sz',
  { dir: $('#dataDir').value },
  '#dataLog', () => { loadDataDates(); listDataOut(); });
$('#btnRebuild').onclick = () => runTask($('#btnRebuild'), '/api/data/rebuild',
  { date: $('#dataDate').value, base: $('#dataDir').value },
  '#dataLog', () => listDataOut());

$('#btnOpenDataDir').onclick = () => openPath($('#dataDir').value);
$('#btnListDataOut').onclick = () => listDataOut();

async function listDataOut() {
  const d = $('#dataDate').value || '';
  const p = d ? `${$('#dataDir').value}/${d}` : $('#dataDir').value;
  const r = await get('/api/files?path=' + encodeURIComponent(p));
  if (!r.ok) { $('#dataOut').innerHTML = `<div class="empty">${esc(r.error)}</div>`; return; }
  renderFileList('#dataOut', r.entries.filter(e => !e.is_dir),
    (f) => previewFile(f.path, '#dataPreview'));
}

// ------------------------------------------------------------------ 公告
function annoDir() {
  return $('#analyzeAnnoDir').value.trim()
      || (CFG && CFG.workspace && CFG.workspace.anno) || '';
}

async function loadTxt() {
  const r = await get('/api/anno/txt?dir=' + encodeURIComponent(annoDir()));
  if (!r.ok) return;
  txtFiles = r.files || [];
  renderFileList('#txtList', txtFiles, null, {
    checkbox: true, empty: '尚未转储，先执行第 1 步',
    onCheck: (f) => selectedTxt.add(f.path),
    onUncheck: (f) => selectedTxt.delete(f.path),
  });
}

$('#btnLoadTxt').onclick = loadTxt;
$('#btnSelAll').onclick = () => {
  const boxes = $$('#txtList .fchk');
  const allOn = boxes.length && boxes.every(b => b.checked);
  boxes.forEach(b => {
    b.checked = !allOn;
    const f = txtFiles[+b.dataset.i];
    if (b.checked) selectedTxt.add(f.path); else selectedTxt.delete(f.path);
  });
};

$('#btnDump').onclick = () => runTask($('#btnDump'), '/api/anno/dump',
  { dir: annoDir(), clean: $('#dumpClean').checked },
  '#annoLog', (t) => {
    if (t && t.status === 'done') showDumpDone();   // 转储成功打勾，保留 1 分钟
    loadTxt();
  }, { progress: true });

// 转储成功后显示 ✓ 标记，1 分钟后自动消失
let _dumpDoneTimer = null;
function showDumpDone() {
  const el = $('#dumpDone');
  if (!el) return;
  el.style.display = '';
  if (_dumpDoneTimer) clearTimeout(_dumpDoneTimer);
  _dumpDoneTimer = setTimeout(() => { el.style.display = 'none'; }, 60000);
}

// ---- 一键分析（生成控制指令，交给 AI 工作台）----
$('#btnAnalyze').onclick = async () => {
  const ad = $('#analyzeAnnoDir').value.trim();
  const od = $('#analyzeOutDir').value.trim();
  if (!ad) { alert('请填写公告目录'); return; }
  if (!od) { alert('请填写输出目录'); return; }
  const btn = $('#btnAnalyze');
  btn.disabled = true;
  try {
    const r = await post('/api/anno/analyze',
      { anno_dir: ad, output_dir: od, model: $('#annoModel').value });
    if (!r.ok) { alert('生成失败：' + (r.error || '未知错误')); return; }
    const ta = $('#analyzePrompt');
    ta.value = r.prompt;
    ta.style.display = '';
    $('#btnCopyPrompt').style.display = '';
    ta.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (e) {
    alert('请求异常：' + e.message);
  } finally {
    btn.disabled = false;
  }
};
$('#btnCopyPrompt').onclick = () => {
  const txt = $('#analyzePrompt').value;
  const done = () => { $('#btnCopyPrompt').textContent = '已复制 ✓'; };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(txt).then(done, () => fallbackCopy(txt, done));
  } else {
    fallbackCopy(txt, done);
  }
};
function fallbackCopy(txt, done) {
  const ta = document.createElement('textarea');
  ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); done(); } catch (e) {}
  document.body.removeChild(ta);
}

// 目录浏览：网页内目录浏览器（不依赖系统弹框；已放开到本机盘符，可从 C:/ 开始）
let DP_TARGET = null;   // 当前正在填哪个输入框

const dpIsDrive = (p) => /^[a-zA-Z]:\/?$/.test(p || '');

// 左侧导航栏：快速访问（工作区）+ 此电脑（各盘符）
function dpBuildRail(roots) {
  const all = roots || [];
  const drives = all.filter(dpIsDrive);
  const ws = all.filter(p => !dpIsDrive(p));
  let html = '';
  if (ws.length) {
    html += '<div class="dp-rail-sec">快速访问</div>';
    ws.forEach(p => {
      const label = p.split('/').filter(Boolean).pop() || p;
      html += '<div class="dp-rail-item" data-path="' + p + '" title="' + p + '">📁 ' + label + '</div>';
    });
  }
  if (drives.length) {
    html += '<div class="dp-rail-sec">此电脑</div>';
    drives.forEach(p => {
      html += '<div class="dp-rail-item" data-path="' + p + '">💾 本地磁盘 (' + p.replace(/\//g, '') + ')</div>';
    });
  }
  const rail = $('#dpRail');
  rail.innerHTML = html;
  $$('#dpRail .dp-rail-item').forEach(it => { it.onclick = () => dpLoad(it.dataset.path); });
}

async function dpLoad(path) {
  const list = $('#dpList');
  list.innerHTML = '<div class="faint" style="padding:10px">加载中…</div>';
  try {
    const r = await get('/api/file/dirs?path=' + encodeURIComponent(path || ''));
    if (!r.ok) { list.innerHTML = '<div class="err" style="padding:10px">' + (r.error || '读取失败') + '</div>'; return; }
    const atComputer = r.path === '@computer';
    $('#dpAddr').value = atComputer ? '' : (r.path || '');
    // 停在「此电脑」时不覆盖已选路径；否则把当前目录作为默认选中项（直接点「选择此文件夹」即可）
    if (!atComputer) $('#dpSel').value = r.path || '';
    $('#dpUp').disabled = !r.parent;
    $('#dpUp').dataset.parent = r.parent || '';
    dpBuildRail(r.roots);
    $$('#dpRail .dp-rail-item').forEach(it => it.classList.toggle('on', it.dataset.path === r.path));
    if (r.error) { list.innerHTML = '<div class="err" style="padding:10px">' + r.error + '</div>'; return; }
    if (!r.dirs.length) {
      list.innerHTML = '<div class="faint" style="padding:10px">（无子目录）</div>';
      return;
    }
    list.innerHTML = r.dirs.map(d =>
      '<div class="dp-item" data-path="' + d.path + '">📁 ' + d.name + '</div>'
    ).join('');
    $$('#dpList .dp-item').forEach(it => {
      it.onclick = () => { $('#dpSel').value = it.dataset.path; $$('#dpList .dp-item').forEach(x => x.classList.remove('on')); it.classList.add('on'); };
      it.ondblclick = () => dpLoad(it.dataset.path);
    });
  } catch (e) {
    list.innerHTML = '<div class="err" style="padding:10px">' + e.message + '</div>';
  }
}

function dpOpen(targetId) {
  DP_TARGET = targetId;
  const cur = ($('#' + targetId) || {}).value || '';
  $('#dirMask').style.display = 'flex';
  dpLoad(cur.trim());
}

function dpClose() { $('#dirMask').style.display = 'none'; DP_TARGET = null; }

$('#dpClose').onclick = dpClose;
$('#dpCancel').onclick = dpClose;
$('#dirMask').onclick = (e) => { if (e.target === $('#dirMask')) dpClose(); };
$('#dpUp').onclick = () => { const p = $('#dpUp').dataset.parent; if (p) dpLoad(p); };
// 地址栏：输入路径回车 / 点「转到」直接跳转（留空则回到「此电脑」）
const dpGo = () => {
  const v = $('#dpAddr').value.trim();
  dpLoad(v || '@computer');
};
$('#dpGo').onclick = dpGo;
$('#dpAddr').onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); dpGo(); } };
$('#dpOk').onclick = () => {
  const v = $('#dpSel').value.trim();
  if (!v) { alert('请先选择或填写目录路径'); return; }
  if (DP_TARGET && $('#' + DP_TARGET)) {
    $('#' + DP_TARGET).value = v.replace(/\\/g, '/');
    if (DP_TARGET === 'analyzeAnnoDir' && $('#dumpDirHint')) $('#dumpDirHint').textContent = v.replace(/\\/g, '/');
  }
  dpClose();
};

$$('.browse').forEach(b => { b.onclick = () => dpOpen(b.dataset.target); });

$('#btnDigest').onclick = async () => {
  const files = Array.from(selectedTxt);
  if (!files.length) { alert('请先勾选要精读的文本'); return; }
  // 流程判断跟随「公告精读模式」（独立于全局后端）：桥接=面板回填，直连=内联进度
  const backend = (CFG && CFG.anno && CFG.anno.backend) || 'workbuddy';
  if (backend === 'workbuddy') {
    // 若已有在填的 json，先确认是否重新开始（保持「只留最新一批」）
    const pend = await get('/api/bridge/pending');
    const items = (pend && pend.items) || [];
    if (items.length) {
      const total = (pend && pend.total) || items.length;
      const cur = items[0].seq || (total - items.length + 1);
      const again = await showConfirm(
        `目前已有正在填充的 json，进程为 ${cur}/${total}，是否重新开始？`,
        '重新开始', '取消');
      if (!again) return;  // 取消：保留当前进度
    }
    const r = await post('/api/anno/digest',
      { files, model: $('#annoModel').value, restart: items.length > 0 });
    if (!r.ok) { alert('启动失败：' + (r.error || '未知错误')); return; }
    loadBridge();
    // 订阅 digest 任务流：进度条 + 执行日志直接在本页（也可靠右栏/侧栏的同一页面）实时可见
    if (r.task) watchAnnoTask(r.task.id);
    alert('已启动精读任务，进度条与执行日志会实时显示在本页（页面打开即自动挂载，无需从本页启动）。\n请在「桥接」面板复制对应 prompt 交给 WorkBuddy，把返回的 JSON 贴回「结果」框提交。');
  } else {
    const prog = $('#annoProgress');
    prog.style.display = 'block';
    prog.querySelector('div').style.width = '0%';
    await runTask($('#btnDigest'), '/api/anno/digest',
      { files, model: $('#annoModel').value }, '#annoLog', (t) => {
        prog.querySelector('div').style.width = '100%';
        const res = t.result || {};
        renderAnnoRows(res.rows || [], res.failed || [], res.skipped || []);
      }, { progress: true });
    prog.style.display = 'none';
  }
};

function renderAnnoRows(rows, failed, skipped) {
  if (!rows.length) {
    $('#annoRows').innerHTML = '<div class="empty">没有成功提炼的记录</div>';
  } else {
    const cols = ['公告日期', '上市公司', '可交换债', '证券代码', '标的股票', '股票代码', '换股价格', '公告性质', '内容摘要'];
    $('#annoRows').innerHTML = `<div class="toolbar">
        <b>精读结果 ${rows.length} 行</b><span class="spacer"></span>
        <span class="faint">摘要可直接编辑，改完点「保存精读结果」</span></div>
      <div class="tablewrap"><table><thead><tr>${cols.map(c => `<th>${c}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((r, i) => '<tr>' + cols.map(c =>
      `<td><textarea rows="${c === '内容摘要' ? 4 : 1}" data-r="${i}" data-c="${c}">${esc(r[c] || '')}</textarea></td>`
    ).join('') + '</tr>').join('')}</tbody></table></div>`;
    window.__annoRows = JSON.parse(JSON.stringify(rows));
    $('#annoRows').querySelectorAll('textarea').forEach(ta => {
      ta.onchange = () => {
        window.__annoRows[+ta.dataset.r][ta.dataset.c] = ta.value;
      };
    });
  }
  const warn = [];
  if (skipped.length) warn.push(`跳过 ${skipped.length} 份（担保人财报等）：${skipped.map(s => s.file.split(/[\\/]/).pop()).join('、')}`);
  if (failed.length) warn.push(`失败 ${failed.length} 份：${failed.map(f => (f.file.split(/[\\/]/).pop()) + '（' + f.error + '）').join('；')}`);
  if (warn.length) $('#annoRows').innerHTML += `<div class="note warn" style="margin-top:10px">${esc(warn.join('<br>'))}</div>`;
}

$('#btnAnnoSave').onclick = async () => {
  const rows = window.__annoRows || [];
  if (!rows.length) { alert('还没有精读结果'); return; }
  const r = await post('/api/anno/save', { rows, dir: annoDir() });
  if (r.ok) alert(`已保存 ${r.count} 行到\n${r.path}`);
  else alert('保存失败：' + r.error);
};

$('#btnAnnoCheck').onclick = () => runTask($('#btnAnnoCheck'), '/api/anno/check',
  { dir: annoDir() }, '#annoLog', null);

$('#btnAnnoBuild').onclick = () => runTask($('#btnAnnoBuild'), '/api/anno/build',
  { dir: annoDir() }, '#annoLog', (t) => {
    const outs = (t.result || {}).outputs || [];
    renderFileList('#annoOut', outs, (f) => previewFile(f.path, '#annoRows'));
  });

// ------------------------------------------------------------------ 舆情
async function loadWechat() {
  const s = await get('/api/wechat/suggest');
  $('#wcSuggest').innerHTML = `当前时段：<b>${esc(s.keyword)}</b>（${esc(s.period)}）—— 不填关键词就按这个抓。`;
  const r = await get('/api/wechat/articles?dir=' + encodeURIComponent($('#wcDir').value || ''));
  if (!r.ok) return;
  renderFileList('#wcList', r.files, (f) => previewFile(f.path, '#wcPreview'),
    { empty: '尚未抓取' });
}

$('#wcDir').addEventListener('change', loadWechat);
$('#btnRefreshWc').onclick = loadWechat;
$('#btnOpenWc').onclick = () => openPath($('#wcDir').value);
$('#btnCrawl').onclick = () => runTask($('#btnCrawl'), '/api/wechat/crawl',
  {
    keyword: $('#wcKeyword').value.trim(), count: +$('#wcCount').value,
    dir: $('#wcDir').value
  }, '#wcLog', () => loadWechat());

// ------------------------------------------------------------------ 晨会 Report
let rpHtmls = [];

async function loadReport() {
  await loadRpStatus();
  // 触发晨会入库：提示词文本框默认隐藏，不在此自动生成（点「生成 / 刷新提示词」时才弹出）
  await loadRpHtmls();
}

async function loadRpStatus() {
  const r = await get('/api/report/status');
  if (!r.ok) return;
  const flag = (b) => b ? '<span class="tag ok">已就位</span>' : '<span class="tag">缺</span>';
  $('#rpStatus').innerHTML = [
    `<div class="item"><span class="name">Report 根目录</span><span class="meta mono">${esc(r.root)}</span></div>`,
    `<div class="item"><span class="name">_analysis（数据/产物）</span><span class="meta mono">${esc(r.analysis)}</span></div>`,
    `<div class="item"><span class="name">晨会分享分析总表.xlsx</span>${flag(r.has_xlsx)}</div>`,
    `<div class="item"><span class="name">行情缓存 _bt_quote_cache_full.json</span>${flag(r.has_quotes)}</div>`,
    `<div class="item"><span class="name">代码表 codemap_qt.json</span>${flag(r.has_codemap)}</div>`,
    `<div class="item"><span class="name">回测报告 HTML</span>${flag(r.has_html)}</div>`,
    `<div class="item"><span class="name">已转 txt / 已提取 json</span><span class="meta">${r.n_txt} / ${r.n_anno}</span></div>`,
  ].join('');
}

// 一键入库：不自己跑管线，只把「当前待处理清单」拼成触发 morning-note-ingest skill 的指令
async function loadRpPrompt() {
  const btn = $('#btnRpGenPrompt');
  btn.disabled = true;
  btn.textContent = '生成中…';
  try {
    const r = await get('/api/report/prompt');
    if (!r.ok) {
      $('#rpPromptInfo').textContent = '生成失败：' + (r.error || '未知错误');
      return;
    }
    $('#rpPrompt').value = r.prompt || '';
    $('#rpPrompt').hidden = false; // 生成成功后弹出提示词大输入框
    $('#rpPromptInfo').textContent =
      `晨会 docx 共 ${r.total} 份，待处理 ${r.pending} 份 · 提示词已就绪`;
  } catch (e) {
    $('#rpPromptInfo').textContent = '请求异常：' + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = '生成 / 刷新提示词';
  }
}

$('#btnRpRefresh').onclick = loadReport;
$('#btnRpGenPrompt').onclick = loadRpPrompt;

$('#btnRpCopyPrompt').onclick = () => {
  const txt = $('#rpPrompt').value;
  if (!txt.trim()) { alert('先点「生成 / 刷新提示词」'); return; }
  const btn = $('#btnRpCopyPrompt');
  const done = () => {
    const old = btn.textContent;
    btn.textContent = '已复制 ✓';
    setTimeout(() => { btn.textContent = old; }, 1600);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(txt).then(done, () => fallbackCopy(txt, done));
  } else {
    fallbackCopy(txt, done);
  }
};

$('#btnRpOpenOut').onclick = async () => {
  const r = await get('/api/report/status');
  if (r.ok) openPath(r.analysis);
};

// ---- 三级回测报告：/_analysis 下的 HTML 走 /report_view/ 静态路由内嵌展示
async function loadRpHtmls() {
  let r = null;
  try { r = await get('/api/report/htmls'); }
  catch (e) { r = { ok: false, error: String(e) }; }
  const sel = $('#rpHtmlSel');
  if (!r || !r.ok) {
    sel.innerHTML = '<option value="">（后端接口不可用：请重启 EB-Agent 平台）</option>';
    $('#rpFrame').src = 'about:blank';
    $('#rpHtmlInfo').textContent = '接口 /api/report/htmls 未响应，多半是平台后端还是旧进程';
    return;
  }
  rpHtmls = r.files || [];
  if (!rpHtmls.length) {
    sel.innerHTML = '<option value="">（_analysis 下没有报告 HTML）</option>';
    $('#rpFrame').src = 'about:blank';
    $('#rpHtmlInfo').textContent = '跑一次入库流程后会自动生成';
    return;
  }
  sel.innerHTML = rpHtmls.map((f, i) =>
    `<option value="${esc(f.rel)}">${esc(f.name)}（${fmtSize(f.size)} · ${fmtTime(f.mtime)}）</option>`
  ).join('');
  // 默认选「板块」报告；没有就选第一份
  let idx = rpHtmls.findIndex((f) => f.name.includes('板块'));
  if (idx < 0) idx = 0;
  sel.selectedIndex = idx;
  rpShowHtml();
}

function rpCurRel() {
  return $('#rpHtmlSel').value || '';
}

let rpLoadedMtime = 0;

function rpShowHtml(force) {
  const rel = rpCurRel();
  const fr = $('#rpFrame');
  if (!rel) { fr.src = 'about:blank'; rpLoadedMtime = 0; return; }
  const url = '/report_view/' + encodeURI(rel);
  const f = rpHtmls.find((x) => x.rel === rel);
  // 切回本页时不无谓重载 833KB；只有文件本身更新过（mtime 变了）才自动刷新
  if (!force && fr.getAttribute('src') === url && f && f.mtime === rpLoadedMtime) return;
  fr.src = url;
  rpLoadedMtime = f ? f.mtime : 0;
  $('#rpHtmlInfo').textContent = f ? `${f.rel} · ${fmtTime(f.mtime)}` : rel;
}

$('#rpHtmlSel').onchange = () => rpShowHtml(true);
$('#btnRpReload').onclick = () => rpShowHtml(true);
$('#btnRpOpenHtml').onclick = () => {
  const rel = rpCurRel();
  if (rel) window.open('/report_view/' + encodeURI(rel), '_blank');
};
$('#btnRpFull').onclick = () => {
  const fr = $('#rpFrame');
  fr.classList.toggle('full');
  $('#btnRpFull').textContent = fr.classList.contains('full') ? '退出全屏' : '全屏';
};
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && $('#rpFrame').classList.contains('full')) $('#btnRpFull').click();
});

// ------------------------------------------------------------------ 设置

// 服务商预设：主流厂商都兼容 OpenAI Chat Completions 协议（base_url + /chat/completions、
// Bearer 鉴权），所以换厂商只需换「接口地址 + 模型名 + Key」三项。新增厂商往这里加一条即可。
// 注意：模型 id 厂商会迭代，预设里给的是通用可用款，填进去后仍可手改。
const PROVIDERS = [
  { id: 'sensenova',  name: '商汤 SenseNova',  base: 'https://token.sensenova.cn/v1',                     model: 'deepseek-v4-flash',           env: 'SENSENOVA_API_KEY' },
  { id: 'deepseek',   name: 'DeepSeek 深度求索', base: 'https://api.deepseek.com/v1',                       model: 'deepseek-chat',               env: 'DEEPSEEK_API_KEY' },
  { id: 'zhipu',      name: '智谱 GLM',         base: 'https://open.bigmodel.cn/api/paas/v4',              model: 'glm-4-flash',                 env: 'ZHIPU_API_KEY' },
  { id: 'qwen',       name: '阿里通义 / 百炼',   base: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus',                   env: 'DASHSCOPE_API_KEY' },
  { id: 'kimi',       name: '月之暗面 Kimi',     base: 'https://api.moonshot.cn/v1',                        model: 'kimi-k2',                     env: 'MOONSHOT_API_KEY' },
  { id: 'minimax',    name: 'MiniMax',          base: 'https://api.minimaxi.com/v1',                       model: 'MiniMax-M2',                  env: 'MINIMAX_API_KEY' },
  { id: 'qianfan',    name: '百度千帆',          base: 'https://qianfan.baidubce.com/v2',                   model: 'ernie-4.0-8k',                env: 'QIANFAN_API_KEY' },
  { id: 'ark',        name: '火山方舟 / 豆包（模型名填接入点 ID）', base: 'https://ark.cn-beijing.volces.com/api/v3', model: '',                      env: 'ARK_API_KEY' },
  { id: 'siliconflow',name: '硅基流动',          base: 'https://api.siliconflow.cn/v1',                      model: 'Qwen/Qwen2.5-72B-Instruct',   env: 'SILICONFLOW_API_KEY' },
  { id: 'openai',     name: 'OpenAI',           base: 'https://api.openai.com/v1',                         model: 'gpt-4o-mini',                 env: 'OPENAI_API_KEY' },
];

let PROVIDER_DIRTY = false;   // 切过预设 → 保存时清掉旧厂商遗留的兜底模型名

function initProviderSelect(baseUrl) {
  const sel = $('#cfgProvider');
  sel.innerHTML = '<option value="">自定义 / 手动填写</option>' +
    PROVIDERS.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  const norm = (u) => (u || '').replace(/\/+$/, '');
  const hit = PROVIDERS.find(p => norm(p.base) === norm(baseUrl));
  sel.value = hit ? hit.id : '';
  PROVIDER_DIRTY = false;
  const note = $('#cfgProviderNote');
  if (note) { note.style.display = 'none'; note.textContent = ''; }
}

function applyProvider() {
  const p = PROVIDERS.find(x => x.id === $('#cfgProvider').value);
  if (!p) return;
  $('#cfgBase').value = p.base;
  if (p.model) $('#cfgModel').value = p.model;
  PROVIDER_DIRTY = true;   // 旧兜底模型名在新厂商几乎必然失效，保存时清空
  const note = $('#cfgProviderNote');
  if (note) {
    note.style.display = 'block';
    note.innerHTML = p.model
      ? `已填入 <b>${esc(p.name)}</b> 的接口地址与默认模型。接下来把 API Key 换成<b>该厂商</b>的 Key，再点「测试连接」验证，通过后保存即可。`
      : `已填入 <b>${esc(p.name)}</b> 的接口地址。该平台模型名需填控制台里的<b>接入点 ID</b>（ep- 开头），填好后同样用「测试连接」验证。`;
  }
}

async function loadSettings() {
  const r = await get('/api/config');
  if (!r.ok) return;
  CFG = r.config;
  const z = CFG.llm;
  $('#cfgKey').value = '';
  $('#cfgKey').placeholder = z.api_key_masked || '未配置';
  $('#cfgBase').value = z.base_url;
  $('#cfgModel').value = z.model || '';
  initProviderSelect(z.base_url);
  $('#cfgTemp').value = z.temperature;
  $('#cfgTimeout').value = z.timeout || 180;
  $('#cfgBackend').value = z.backend || 'api';
  syncBackendUI();
  syncAnnoUI();
  syncAstUI();
  $('#cfgPython').value = CFG.python.executable || '';
  $('#cfgPath').textContent = CFG.paths.config;

  const sel = $('#annoModel');
  // 精读（桥接）默认用 hy3：把它排在最前并预选
  const annoModel = (CFG.anno && CFG.anno.model) || 'hy3';
  const models = [annoModel, z.model].concat(z.fallback_models || []).filter((v, i, a) => v && a.indexOf(v) === i);
  sel.innerHTML = models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
  sel.value = annoModel;

  loadDeps();
  initTerminal();
}

async function loadDeps() {
  const r = await get('/api/env');
  if (!r.ok) return;
  const items = (r.deps || []).map(d => `
    <div class="item"><span class="badge ${d.installed ? 'ok' : 'err'}">${d.installed ? '已装' : '缺'}</span>
      <span class="name">${esc(d.label)} <span class="faint mono">${esc(d.pip)}</span>
        <div class="faint" style="font-size:12px">${esc(d.why)}</div></span>
      ${d.installed ? '' : `<button class="btn-sm" data-pip="${esc(d.pip)}">安装</button>`}</div>`).join('');
  $('#depList').innerHTML = `<div class="filelist">${items}</div>`;
  $('#depList').querySelectorAll('button[data-pip]').forEach(b => {
    b.onclick = async () => {
      b.disabled = true; b.textContent = '安装中…';
      const res = await post('/api/env/install', { package: b.dataset.pip });
      if (res.ok) watchTask(res.task.id, '#dataLog', () => loadDeps());
      else { alert('启动安装失败：' + res.error); b.disabled = false; }
    };
  });
}

// ------------------------------------------------------------------ 终端交互
let TERM_TID = null;
let TERM_ES = null;
let TERM_HIST = [];
let TERM_HIST_IDX = -1;

function initTerminal() {
  const inp = $('#termInput');
  if (!inp || inp.dataset.bound) return;
  inp.dataset.bound = '1';
  $('#btnTermRun').onclick = runTermCmd;
  $('#btnTermStop').onclick = stopTermCmd;
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); runTermCmd(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); histNav(-1, inp); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); histNav(1, inp); }
  });
}

function histNav(dir, inp) {
  if (!TERM_HIST.length) return;
  TERM_HIST_IDX = Math.max(0, Math.min(TERM_HIST.length, TERM_HIST_IDX + dir));
  inp.value = TERM_HIST[TERM_HIST_IDX] || '';
  // 光标移到末尾
  setTimeout(() => { inp.selectionStart = inp.selectionEnd = inp.value.length; }, 0);
}

function termSetRunning(on) {
  $('#btnTermRun').disabled = on;
  $('#btnTermStop').style.display = on ? '' : 'none';
  $('#termBadge').textContent = on ? '运行中' : '空闲';
  $('#termBadge').className = on ? 'badge warn' : 'badge';
}

async function runTermCmd() {
  const inp = $('#termInput');
  const cmd = (inp.value || '').trim();
  if (!cmd || TERM_TID) return;          // 已有任务在跑则忽略
  TERM_HIST.push(cmd);
  TERM_HIST_IDX = TERM_HIST.length;
  const out = $('#termOut');
  out.textContent += '$ ' + cmd + '\n';
  out.scrollTop = out.scrollHeight;

  const r = await post('/api/terminal', { command: cmd });
  if (!r || !r.ok || !r.tid) {
    out.textContent += (r && r.error ? r.error : '启动失败') + '\n';
    out.scrollTop = out.scrollHeight;
    return;
  }
  TERM_TID = r.tid;
  termSetRunning(true);

  if (TERM_ES) { try { TERM_ES.close(); } catch (e) {} }
  const es = new EventSource('/api/terminal/stream?tid=' + encodeURIComponent(r.tid));
  TERM_ES = es;
  const onOut = (e) => {
    try { const d = JSON.parse(e.data); out.textContent += d.text; out.scrollTop = out.scrollHeight; } catch (_) {}
  };
  es.addEventListener('output', onOut);
  es.addEventListener('meta', (e) => {
    try { const d = JSON.parse(e.data); out.textContent += '[工作目录] ' + d.cwd + '\n'; out.scrollTop = out.scrollHeight; } catch (_) {}
  });
  es.addEventListener('status', (e) => {
    try { const d = JSON.parse(e.data); out.textContent += '\n[exit ' + d.exit_code + (d.killed ? ' · 已终止' : '') + ']\n'; } catch (_) {}
    finishTerm();
  });
  es.addEventListener('error', () => { finishTerm(); });
  es.addEventListener('end', () => { finishTerm(); });
}

function finishTerm() {
  termSetRunning(false);
  if (TERM_ES) { try { TERM_ES.close(); } catch (e) {} TERM_ES = null; }
  if (TERM_TID) {
    // 终止后顺手清掉后端会话，避免长期占用
    post('/api/terminal/stop', { tid: TERM_TID }).catch(() => {});
    TERM_TID = null;
  }
}

async function stopTermCmd() {
  if (!TERM_TID) return;
  await post('/api/terminal/stop', { tid: TERM_TID });
}

function collectCfg() {
  const llm = {
    backend: $('#cfgBackend').value,
    api_key: $('#cfgKey').value.trim(),   // 空串表示不改
    base_url: $('#cfgBase').value.trim(),
    temperature: parseFloat($('#cfgTemp').value) || 0.2,
    timeout: parseInt($('#cfgTimeout').value, 10) || 180,
  };
  const model = $('#cfgModel').value.trim();
  if (model) llm.model = model;           // 留空不覆盖，避免把已有模型名刷没
  const p = PROVIDERS.find(x => x.id === $('#cfgProvider').value);
  if (p && p.env) llm.env_key = p.env;
  // 换厂商后，旧厂商的兜底模型名在新平台几乎必然 404，顺手清空
  if (PROVIDER_DIRTY) llm.fallback_models = [];
  return {
    llm,
    python: { executable: $('#cfgPython').value.trim() },
  };
}

  // 全局后端切换：只影响通用 LLM 设置的 Key 字段与提示
  function syncBackendUI() {
    const b = $('#cfgBackend').value;
    const isApi = b === 'api';
    $('#cfgKeyField').style.display = isApi ? '' : 'none';
    $('#cfgWbHint').style.display = (b === 'workbuddy') ? 'block' : 'none';
    syncAnnoUI();
  }
  // 点击切换用的圆角按钮渲染：workbuddy=绿，api=蓝
  function renderModePill(el, backend, onToggle) {
    if (!el) return;
    const wb = (backend || 'workbuddy') === 'workbuddy';
    el.classList.toggle('is-wb', wb);
    el.classList.toggle('is-api', !wb);
    el.textContent = wb ? 'WorkBuddy 桥接' : '云端 API 直连';
    el.title = '点击切换：' + (wb ? '当前桥接，点此切到云端直连' : '当前直连，点此切到桥接');
    el.onclick = onToggle;
  }
  // 公告精读模式：控制公告页「桥接」面板显隐 + 标题徽标；读 config 而非下拉
  function syncAnnoUI() {
    const ab = (CFG && CFG.anno && CFG.anno.backend) || 'workbuddy';
    const astb = (CFG && CFG.assistant && CFG.assistant.backend) || 'api';
    // 桥接面板同时服务于「公告精读」与「对话助手」两种桥接：任一为桥接即显示，
    // 否则对话助手切到桥接时会指向一个看不见的面板（找不到）。
    $('#bridgeCard').style.display = (ab === 'workbuddy' || astb === 'workbuddy') ? '' : 'none';
    renderModePill($('#annoBackendBadge'), ab, toggleAnnoBackend);
  }
  async function toggleAnnoBackend() {
    const cur = (CFG && CFG.anno && CFG.anno.backend) || 'workbuddy';
    const next = cur === 'workbuddy' ? 'api' : 'workbuddy';
    const res = await post('/api/config', { anno: { backend: next } });
    if (!res.ok) { alert('保存失败：' + (res.error || '未知')); return; }
    if (res.config) CFG = res.config;
    syncAnnoUI();
  }
  // 对话助手模式：标题徽标 + 模型条模式文案
  function syncAstUI() {
    const ab = (AST.busy) ? null : ((CFG && CFG.assistant && CFG.assistant.backend) || 'api');
    const badge = $('#astModeBadge');
    if (badge) {
      if (AST.busy) { badge.textContent = '处理中…'; badge.className = 'badge mode-pill'; }
      else renderModePill(badge, ab, toggleAstBackend);
    }
    renderAssistantModels();
  }
  async function toggleAstBackend() {
    const cur = (CFG && CFG.assistant && CFG.assistant.backend) || 'api';
    const next = cur === 'workbuddy' ? 'api' : 'workbuddy';
    const res = await post('/api/config', { assistant: { backend: next } });
    if (!res.ok) { alert('保存失败：' + (res.error || '未知')); return; }
    if (res.config) CFG = res.config;
    syncAstUI();
    syncAnnoUI();   // 助手切桥接/直连也要刷新公告页「桥接」面板的显隐
  }
  $('#cfgBackend').onchange = syncBackendUI;
$('#cfgProvider').onchange = applyProvider;

  // ---- WorkBuddy 桥接面板 ----
  async function loadBridge() {
    const r = await get('/api/bridge/pending');
    if (!r.ok) return;
    renderBridge(r.items || [], r.total || 0);
  }
  // 始终只有一个输入框：当前待回填项；其余在队列里，提交后自动前进。
  function renderBridge(items, total) {
    const el = $('#bridgeList');
    if (!items.length) {
      el.innerHTML = '<div class="empty">暂无待处理 prompt（已全部回填完成，或尚未开始精读）</div>';
      return;
    }
    total = total || items.length;
    const cur = items[0].seq || (total - items.length + 1);
    const pct = total > 0 ? Math.round(((cur - 1) / total) * 100) : 0;
    const it = items[0];
    el.innerHTML = `
      <div class="bridge-item" data-id="${esc(it.id)}">
        <div class="toolbar"><b>进程 ${cur} / ${total}</b><span class="spacer"></span>
          <span class="faint">${esc(it.name || it.id)}</span></div>
        <div class="progress"><div style="width:${pct}%"></div></div>
        <div class="toolbar">
          <button class="btn-sm" data-act="toggle">查看 prompt</button>
          <button class="btn-sm" data-act="copy">复制 prompt</button>
          <span class="faint">剩余 ${items.length} 条待回填</span>
        </div>
        <pre class="bridge-prompt hidden">${esc(it.prompt || '')}</pre>
        <div class="faint" style="margin:6px 0 2px">把 WorkBuddy 返回的 JSON 贴这里 ↓</div>
        <textarea class="bridge-result" rows="4" placeholder='{"公告日期":"...", ...} 或 {"skip":true,"reason":"..."}'></textarea>
        <div class="toolbar"><button class="btn-sm primary" data-act="submit">提交结果</button>
          <span class="bridge-msg faint"></span></div>
      </div>`;
    const box = el.querySelector('.bridge-item');
    const pre = box.querySelector('.bridge-prompt');
    const toggleBtn = box.querySelector('[data-act="toggle"]');
    box.querySelector('[data-act="copy"]').onclick = () => {
      const text = pre.textContent;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          box.querySelector('.bridge-msg').textContent = '已复制';
        });
      } else {
        const ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); document.body.removeChild(ta);
        box.querySelector('.bridge-msg').textContent = '已复制';
      }
    };
    toggleBtn.onclick = () => {
      const hidden = pre.classList.toggle('hidden');
      toggleBtn.textContent = hidden ? '查看 prompt' : '收起 prompt';
    };
    box.querySelector('[data-act="submit"]').onclick = async () => {
      const content = box.querySelector('.bridge-result').value.trim();
      if (!content) { box.querySelector('.bridge-msg').textContent = '请先粘贴结果'; return; }
      const res = await post('/api/bridge/submit', { id: it.id, content });
      box.querySelector('.bridge-msg').textContent = res.ok ? '已提交，任务续跑中' : ('失败：' + (res.error || ''));
      if (res.ok) setTimeout(loadBridge, 800);
    };
  }
  $('#btnRefreshBridge').onclick = loadBridge;

  // 通用确认弹窗（返回 Promise<bool>）
  function showConfirm(msg, okText, cancelText) {
    return new Promise(resolve => {
      $('#modalMsg').textContent = msg;
      $('#modalOk').textContent = okText || '确定';
      $('#modalCancel').textContent = cancelText || '取消';
      const mask = $('#modalMask');
      mask.style.display = 'flex';
      const done = (v) => { mask.style.display = 'none'; resolve(v); };
      $('#modalOk').onclick = () => done(true);
      $('#modalCancel').onclick = () => done(false);
    });
  }

const saveCfg = async (msg) => {
  const r = await post('/api/config', collectCfg());
  if (r.ok) { alert(msg || '已保存'); applyCfg(r.config); }
  else alert('保存失败：' + r.error);
};
$('#btnSaveCfg').onclick = () => saveCfg();
$('#btnSaveCfg2').onclick = () => saveCfg();

$('#btnDetect').onclick = async () => {
  const r = await post('/api/env/detect', {});
  if (r.ok) {
    $('#cfgPython').value = r.executable;
    alert(`探测到：${r.executable}\nPython ${r.version}\n已装依赖：${(r.packages || []).join('、') || '无'}`);
    loadDeps();
  } else alert('探测失败：' + r.error);
};

$('#btnTestLlm').onclick = async () => {
  const el = $('#llmTestResult');
  el.innerHTML = '<span class="faint">测试中…</span>';
  const r = await post('/api/llm/test', {});
  if (r.ok) {
    const extra = r.message ? ` · ${esc(r.message)}` : ` · ${r.elapsed}s`;
    el.innerHTML = `<span class="badge ok">就绪</span> ${esc(r.model || '')}${extra}`;
    $('#llmDot').className = 'dot ok';
    $('#llmDot').title = r.message || `后端 ${r.model}`;
  } else {
    el.innerHTML = `<span class="badge err">失败</span> ${esc(r.message || r.error)}
      ${r.hint ? `<div class="faint" style="margin-top:4px">${esc(r.hint)}</div>` : ''}`;
    $('#llmDot').className = 'dot err';
  }
};

function applyCfg(c) {
  CFG = c;
  $('#dataDir').value = c.workspace.data;
  $('#wcDir').value = c.workspace.wechat;
  // 一键分析：默认公告目录=Anno 工作区，输出目录=平台产出目录
  $('#analyzeAnnoDir').value = c.workspace.anno;
  $('#analyzeOutDir').value = c.workspace.output;
  // 转储沿用上方「公告目录」
  const dh = $('#dumpDirHint'); if (dh) dh.textContent = c.workspace.anno || '—';
}

// ------------------------------------------------------------------ 对话助手
let AST = { session: null, busy: false, inited: false };

const AST_CHIP_UTTER = {
  anno_digest: '帮我一键精读公告',
  anno_dump: '转储公告 PDF',
  anno_build: '生成整理表',
  anno_check: '校验公告',
  anno_analyze: '帮我生成一键分析指令',
  data_rebuild: '重建数据总表',
  data_download_xx: '下载中证估值',
  data_download_sz: '下载深交所逐笔',
  wechat_crawl: '抓取舆情热文',
  wechat_summarize: '总结今日午盘舆情',
  task_status: '查看最近任务',
  overview: '看看工作台总览',
};

function astSetBusy(b) {
  AST.busy = b;
  $('#btnSend').disabled = b;
  $('#chatInput').disabled = b;
  syncAstUI();
}

/** 新建一条气泡（user=右对齐蓝色；bot=左对齐白卡）。 */
function astBox(kind) {
  const box = $('#chatBox');
  const d = document.createElement('div');
  d.className = 'chat-msg ' + kind;
  box.appendChild(d);
  box.scrollTop = box.scrollHeight;
  return d;
}

function astText(bubble, text, cls) {
  const body = document.createElement('div');
  body.className = 'chat-body' + (cls ? ' ' + cls : '');
  body.textContent = String(text == null ? '' : text).replace(/\*\*/g, '');
  bubble.appendChild(body);
  return body;
}

/** 在气泡里追加「来源」徽标行 + 参考文献清单（Agentic RAG 透明展示）。 */
function astSources(bubble, groups) {
  if (!groups || !groups.length) return;
  const row = document.createElement('div');
  row.className = 'chat-srcs';
  groups.forEach(g => {
    const s = document.createElement('span');
    s.className = 'badge ok';
    s.textContent = '已检索 ' + (g.label || g.source || '?') + ' ×' + (g.count || 0);
    row.appendChild(s);
  });
  bubble.appendChild(row);
  // 参考文献：把各源的 refs 压平，显示标题 + 原文链接
  const refs = [];
  groups.forEach(g => (g.refs || []).forEach(it => { if (it && it.ref) refs.push(it); }));
  renderRefList(bubble, refs);
}

/** 渲染参考文献清单（标题 + 原文链接 / 本地文档链接）。refs: [{title, url, path, source}] */
function renderRefList(bubble, refs) {
  if (!refs || !refs.length) return;
  const h = document.createElement('div');
  h.className = 'chat-body dim ref-head';
  h.textContent = '📎 参考文献';
  bubble.appendChild(h);
  const ul = document.createElement('div');
  ul.className = 'ref-list';
  refs.forEach(it => {
    const line = document.createElement('div');
    line.className = 'ref-item';
    const t = document.createElement('span');
    t.className = 'ref-title';
    t.textContent = it.title || it.path || it.ref || '未命名文档';
    line.appendChild(t);
    const fp = it.path || it.ref || '';
    if (it.url) {
      const a = document.createElement('a');
      a.className = 'ref-link';
      a.href = it.url; a.target = '_blank'; a.rel = 'noopener';
      a.textContent = ' 原文↗';
      line.appendChild(a);
    } else if (fp) {
      // 旧抓取未存原文链接：退化为打开本地 docx
      const a = document.createElement('a');
      a.className = 'ref-link';
      a.href = 'file:///' + fp.replace(/\\/g, '/');
      a.textContent = ' 打开文档↗';
      line.appendChild(a);
    }
    ul.appendChild(line);
  });
  bubble.appendChild(ul);
}

function astScroll() { const box = $('#chatBox'); box.scrollTop = box.scrollHeight; }

/** 统一渲染后端一条响应（confirm / action / qa / error）。 */
function astHandleRes(r) {
  if (!r || !r.ok) {
    AST.mode = 'error';
    const b = astBox('bot');
    astText(b, (r && (r.error || r.message)) || '未知错误', 'err');
    astScroll();
    return;
  }
  if (r.session) AST.session = r.session;
  if (r.kind === 'confirm') { AST.mode = '待确认'; astConfirm(r); return; }
  if (r.kind === 'action') { AST.mode = r.mode === 'sync' ? '已返回' : (r.mode === 'bridge' ? '需桥接' : '任务'); astAction(r); return; }
  if (r.kind === 'qa') { AST.mode = r.mode === 'llm' ? '模型' : (r.mode === 'bridge' ? '需桥接' : '本地'); astQa(r); return; }
  AST.mode = 'error';
  const b = astBox('bot');
  astText(b, (r && (r.error || r.message)) || '未识别的返回', 'err');
  astScroll();
}

function astConfirm(r) {
  const b = astBox('bot');
  const modeTxt = r.mode === 'bridge' ? '需桥接' : (r.mode === 'auto' ? '全自动' : '');
  const head = document.createElement('div');
  head.className = 'chat-body strong';
  head.textContent = (r.icon || '▶') + ' ' + (r.message || ('将要执行：' + (r.label || r.action)));
  b.appendChild(head);
  (r.preview || []).forEach(p => {
    const li = document.createElement('div');
    li.className = 'chat-body dim small';
    li.textContent = '· ' + p;
    b.appendChild(li);
  });
  const bar = document.createElement('div');
  bar.className = 'chat-acts';
  bar.innerHTML =
    (modeTxt ? `<span class="badge ${r.mode === 'bridge' ? 'warn' : 'ok'}">${esc(modeTxt)}</span>` : '')
    + '<button class="btn-primary btn-sm" data-ok="1">确认执行</button>'
    + '<button class="btn-sm" data-no="1">取消</button>';
  b.appendChild(bar);
  bar.querySelector('[data-ok]').onclick = async () => {
    bar.querySelectorAll('button').forEach(x => x.disabled = true);
    astSetBusy(true);
    try {
      const rr = await post('/api/assistant', {
        confirm: true, action: r.action, params: r.params || {}, session: AST.session
      });
      astHandleRes(rr);
    } catch (e) {
      astText(astBox('bot'), '请求异常：' + e.message, 'err');
    } finally { astSetBusy(false); }
  };
  bar.querySelector('[data-no]').onclick = () => {
    bar.remove();
    astText(b, '已取消，没有执行任何操作。', 'dim small');
  };
  astScroll();
}

function astAction(r) {
  const b = astBox('bot');
  const modeTxt = r.mode === 'bridge' ? '需桥接' : (r.mode === 'auto' ? '全自动' : (r.mode === 'sync' ? '已返回' : ''));
  astText(b, (r.icon || '▶') + ' ' + (r.message || '已执行'), 'strong');
  if (modeTxt) {
    const m = document.createElement('div'); m.className = 'chat-body small';
    m.innerHTML = `<span class="badge ${r.mode === 'bridge' ? 'warn' : 'ok'}">${esc(modeTxt)}</span>`;
    b.appendChild(m);
  }
  if (r.error) { astText(b, r.error, 'err'); astScroll(); return; }

  if (r.task && r.task.id) {
    const log = document.createElement('div');
    log.className = 'log chat-log';
    b.appendChild(log);
    astScroll();
    const follow = r.followUp;   // 非空=抓取完成后自动用已抓内容汇总
    watchTask(r.task.id, log, (t) => {
      const st = t ? (t.status || '') : '';
      const map = { done: '完成 ✓', failed: '失败 ✗', stopped: '已停止', running: '进行中', pending: '排队中' };
      const foot = document.createElement('div');
      foot.className = 'chat-foot';
      foot.textContent = '—— 任务已' + (map[st] || st) + ' ——';
      b.appendChild(foot);
      astScroll();
  if (follow && t) {
    try {
      const sum = (t.result && t.result.summary) || '';
      const meta = (t.result && t.result.summary_meta) || {};
      const outCount = (t.result && t.result.outputs) ? t.result.outputs.length : 0;
      renderWechatSummary(follow, sum, meta, st, outCount);
    } catch (e) { /* 忽略渲染异常 */ }
  }
    });
  } else if (r.data) {
    astRenderData(b, r.data);
    astScroll();
  } else {
    astScroll();
  }
}

/** sync 型动作的返回数据（指令文本 / 任务列表 / 工作台总览）。 */
function astRenderData(b, d) {
  if (!d) return;
  if (d.kind === 'prompt' && d.text) {
    const ta = document.createElement('textarea');
    ta.className = 'bridge-result'; ta.readOnly = true; ta.rows = 10;
    ta.value = d.text;
    b.appendChild(ta);
    const bar = document.createElement('div'); bar.className = 'chat-acts';
    bar.innerHTML = '<button class="btn-sm primary">复制指令</button>';
    b.appendChild(bar);
    bar.querySelector('button').onclick = () => {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(d.text).then(() => { bar.querySelector('button').textContent = '已复制 ✓'; });
      } else { fallbackCopy(d.text, () => { bar.querySelector('button').textContent = '已复制 ✓'; }); }
    };
    return;
  }
  const items = d.items || (d.kind === 'tasks' ? [] : []);
  if (d.kind === 'tasks') {
    const box = document.createElement('div'); box.className = 'filelist chat-list';
    box.innerHTML = items.length ? items.map(t =>
      `<div class="item"><span class="dot ${t.status === 'done' ? 'ok' : (t.status === 'failed' ? 'err' : (t.status === 'running' ? 'warn' : ''))}"></span>
        <span class="name">${esc(t.title)}</span>
        <span class="badge">${esc(t.project || '-')}</span>
        <span class="meta">${esc(t.status)}</span></div>`).join('')
      : '<div class="empty">暂无任务</div>';
    b.appendChild(box);
  } else if (d.kind === 'overview' && d.items) {
    const ov = d.items;
    const o1 = ov.anno || {}, o2 = ov.data || {}, o3 = ov.wechat || {};
    const box = document.createElement('div'); box.className = 'filelist chat-list';
    box.innerHTML =
      `<div class="item"><span class="badge ok">Anno</span><span class="name">${esc(o1.pdf_count || 0)} 份 PDF / ${esc(o1.dump_count || 0)} 份转储 / ${esc(o1.input_rows || 0)} 行精读</span></div>
       <div class="item"><span class="badge ok">Data</span><span class="name">${esc(o2.date_count || 0)} 个日期目录${o2.latest_date ? '（最新 ' + esc(o2.latest_date) + '）' : ''}</span></div>
       <div class="item"><span class="badge ok">Wechat</span><span class="name">${esc(o3.doc_count || 0)} 篇 docx</span></div>`;
    b.appendChild(box);
  }
}

function astQa(r) {
  const b = astBox('bot');
  astSources(b, r.sources);
  astText(b, r.answer);
  const foot = [];
  if (r.mode === 'llm') foot.push(`由 ${esc(r.model || '模型')} 生成 · 检索 ${r.retrieved || 0} 条 · ${r.elapsed || 0}s`);
  if (r.mode === 'local') {
    foot.push('模型暂不可用，以上为本地资料陈列');
    if (r.note) foot.push(esc(r.note));
  }
  if (r.mode === 'bridge') {
    // 在对话气泡内内联桥接 prompt：复制 + 贴回结果，无需跳到「公告」页
    const wrap = document.createElement('div');
    wrap.className = 'bridge-inline';
    wrap.innerHTML =
      '<div class="chat-body small dim">↓ 复制下面的 prompt 交给 WorkBuddy 运行</div>' +
      '<pre class="bridge-prompt">' + esc(r.prompt_text || '') + '</pre>' +
      '<div class="toolbar">' +
        '<button class="btn-sm" data-act="copy">复制 prompt</button>' +
        '<span class="bridge-msg faint"></span>' +
      '</div>' +
      '<div class="faint" style="margin:8px 0 2px">把 WorkBuddy 返回的 JSON/文本贴这里 ↓</div>' +
      '<textarea class="bridge-result" rows="4" placeholder=\'直接粘贴 WorkBuddy 的回复（纯文本或 {"content":"..."}）\'></textarea>' +
      '<div class="toolbar"><button class="btn-sm primary" data-act="submit">提交结果</button></div>';
    b.appendChild(wrap);
    wrap.querySelector('[data-act="copy"]').onclick = () => {
      fallbackCopy(r.prompt_text || '', () => {
        const m = wrap.querySelector('.bridge-msg');
        if (m) m.textContent = '已复制 ✓';
      });
    };
    wrap.querySelector('[data-act="submit"]').onclick = async () => {
      const ta = wrap.querySelector('.bridge-result');
      const raw = (ta.value || '').trim();
      if (!raw) { alert('请先粘贴 WorkBuddy 的返回内容'); return; }
      const btn = wrap.querySelector('[data-act="submit"]');
      btn.disabled = true;
      try {
        await post('/api/bridge/submit', { id: r.prompt_id, content: raw });
        let shown = raw;
        try {
          const o = JSON.parse(raw);
          if (o && typeof o === 'object' && typeof o.content === 'string') shown = o.content;
          else if (o && typeof o === 'object') shown = JSON.stringify(o, null, 2);
        } catch (e) { /* 纯文本，原样展示 */ }
        const head = document.createElement('div');
        head.className = 'chat-body strong';
        head.textContent = '✅ WorkBuddy 归纳回答';
        wrap.appendChild(head);
        astText(wrap, shown);
        ta.remove(); btn.remove();
        astScroll();
      } catch (e) {
        btn.disabled = false;
        alert('提交失败：' + e.message);
      }
    };
    foot.push('已生成桥接 prompt' + (r.prompt_id ? '（id=' + esc(r.prompt_id) + '）' : '') + '，可直接在本对话复制/提交');
  }
  if (foot.length) {
    const f = document.createElement('div');
    f.className = 'chat-foot';
    f.innerHTML = foot.join(' · ');
    b.appendChild(f);
  }
  astScroll();
}

/** 抓取完成后，把 on_done 里自动生成的舆情汇总渲染成一条气泡。
 *  question：原始问题（如"总结今日午盘舆情"）；summary：LLM 汇总文本；
 *  meta：{mode, model, sources}；st：任务最终状态。 */
function renderWechatSummary(question, summary, meta, st, outCount) {
  const b = astBox('bot');
  const head = document.createElement('div');
  head.className = 'chat-body strong';
  head.textContent = '📰 ' + (question || '舆情汇总');
  b.appendChild(head);

  if (summary && summary.trim()) {
    astText(b, summary);
  } else if (st === 'failed') {
    astText(b, '抓取任务失败，无法汇总。可检查网络后重试，或手动在「舆情」页抓取。', 'err');
  } else if (outCount > 0) {
    astText(b, '本次抓取到 ' + outCount + ' 篇公众号文章，但自动汇总未生成内容（模型可能返回为空或被限流）。可稍后重试，或点开目录里的 docx 自行查看。', 'dim');
  } else {
    astText(b, '抓取已完成，但公众号目录里没有命中该时段的相关文章，暂无可汇总内容。',
            'dim');
  }

  // 参考文献清单（抓取链路在 on_done 里已生成 summary_meta.references）
  if (meta && meta.references && meta.references.length) {
    renderRefList(b, meta.references);
  }

  const foot = [];
  if (meta && meta.mode === 'llm') foot.push('由 ' + esc(meta.model || '模型') + ' 生成');
  if (meta && meta.mode === 'local') foot.push('模型暂不可用，以上为本地资料陈列');
  if (meta && meta.sources && meta.sources.length)
    foot.push('检索源：' + meta.sources.join('/'));
  if (foot.length) {
    const f = document.createElement('div');
    f.className = 'chat-foot';
    f.innerHTML = foot.join(' · ');
    b.appendChild(f);
  }
  astScroll();
}

/** 发送一条用户消息（快捷指令也会走到这里）。 */
async function astSend(raw) {
  const text = (raw == null ? '' : String(raw)).trim();
  if (!text || AST.busy) return;
  const empty = $('#chatBox .empty'); if (empty) empty.remove();
  const ub = astBox('user');
  astText(ub, text);
  astScroll();
  astSetBusy(true);
  try {
    const r = await post('/api/assistant', { message: text, session: AST.session });
    if (r && r.session) AST.session = r.session;
    const lab = $('#astSessionLabel');
    if (lab && AST.session) lab.textContent = '会话 ' + AST.session;
    astHandleRes(r);
  } catch (e) {
    astText(astBox('bot'), '请求异常：' + e.message, 'err');
    astScroll();
  } finally { astSetBusy(false); }
}

/** 右侧「可用数据源 + 快捷指令」与底部分类芯片。 */
function wireAstCtxHoverScroll(root) {
  // 鼠标在 value 右半边→向右滚（露出右侧），左半边→向左滚（回到开头）；静止时显示开头。
  root.querySelectorAll('.meta').forEach(m => {
    let raf = 0, mx = 0, hovering = false;
    const step = 1.6;
    function tick() {
      if (!hovering) return;
      const max = m.scrollWidth - m.clientWidth;
      if (max > 2) {
        const rect = m.getBoundingClientRect();
        const frac = (mx - rect.left) / Math.max(rect.width, 1);
        if (frac > 0.5) m.scrollLeft = Math.min(max, m.scrollLeft + step);
        else m.scrollLeft = Math.max(0, m.scrollLeft - step);
      }
      raf = requestAnimationFrame(tick);
    }
    m.addEventListener('mouseenter', (e) => { hovering = true; mx = e.clientX; raf = requestAnimationFrame(tick); });
    m.addEventListener('mousemove', (e) => { mx = e.clientX; });
    m.addEventListener('mouseleave', () => { hovering = false; if (raf) cancelAnimationFrame(raf); raf = 0; m.scrollLeft = 0; });
  });
}

async function astLoadCtx() {
  const el = $('#astCtx');
  try {
    const r = await get('/api/assistant/context');
    if (!r.ok) { el.innerHTML = `<div class="empty">${esc(r.error || '加载失败')}</div>`; return; }
    const items = (r.items || []).map(i =>
      `<div class="item"><span class="name" title="${esc(i.label)}">${esc(i.label)}</span><span class="meta" title="${esc(i.value)}">${esc(i.value)}</span></div>`).join('');
    el.innerHTML = items || '<div class="empty">暂无数据</div>';
    wireAstCtxHoverScroll(el);

    // 底部快捷指令芯片：只放全自动动作 + 2 个常见问答（sync/桥接动作不进芯片）
    const chips = [];
    (r.actions || []).forEach(a => {
      if (!a || a.mode !== 'auto') return;
      chips.push({ label: (a.icon || '▶') + ' ' + a.label, send: AST_CHIP_UTTER[a.name] || ('帮我' + a.label) });
    });
    const chipRow = $('#chipRow');
    const list = chips.slice(0, 7)
      .concat([
        { label: '❓ 问 EB 风险', send: '帮我看看最近公告里可交换债的风险情况' },
        { label: '📊 工作台总览', send: '看看工作台总览' },
      ]);
    chipRow.innerHTML = list.map((c, i) => `<button class="chip${i >= chips.slice(0, 7).length ? ' qa' : ''}">${esc(c.label)}</button>`).join('');
    chipRow.querySelectorAll('.chip').forEach((btn, i) => { btn.onclick = () => astSend(list[i].send); });
  } catch (e) {
    el.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}

async function astLoadHist() {
  const el = $('#astHist');
  try {
    const r = await get('/api/assistant/sessions?limit=30');
    if (!r.ok) { el.innerHTML = `<div class="empty">${esc(r.error || '加载失败')}</div>`; return; }
    const ss = (r.sessions || []);
    el.innerHTML = ss.length ? ss.map(s =>
      `<div class="item hist-item" data-sid="${esc(s.id)}" title="${esc(s.id)}">
        <span class="name">${esc(s.title)}</span>
        <span class="meta">${esc(s.updated_str)} · ${s.turns} 条</span></div>`).join('')
      : '<div class="empty">暂无历史会话</div>';
    el.querySelectorAll('.hist-item').forEach(it => {
      it.onclick = () => astOpenSession(it.dataset.sid);
    });
  } catch (e) {
    el.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}

/** 打开历史会话：回放全部消息，并接续该 session。 */
async function astOpenSession(sid) {
  const empty = $('#chatBox .empty'); if (empty) empty.remove();
  $('#chatBox').innerHTML = '<div class="empty">加载会话中…</div>';
  try {
    const r = await get('/api/assistant/session?id=' + encodeURIComponent(sid));
    $('#chatBox').innerHTML = '';
    if (!r.ok || !r.messages || !r.messages.length) {
      $('#chatBox').innerHTML = '<div class="empty">会话为空</div>';
      AST.session = sid;
      return;
    }
    AST.session = sid;
    const lab = $('#astSessionLabel');
    if (lab) lab.textContent = '会话 ' + sid;
    r.messages.forEach(rec => {
      if (rec.role === 'user') { astText(astBox('user'), rec.text); }
      else if (rec.role === 'assistant') { astText(astBox('bot'), rec.text); }
      else {
        const b = astBox('bot');
        const f = document.createElement('div'); f.className = 'chat-foot';
        f.textContent = '· 执行：' + (rec.text || '').slice(0, 120);
        b.appendChild(f);
      }
    });
    astScroll();
  } catch (e) {
    $('#chatBox').innerHTML = '<div class="empty">加载失败</div>';
  }
}

function astNewChat() {
  AST.session = null;
  $('#chatBox').innerHTML = '<div class="empty">新对话。点下方快捷指令或直接输入。</div>';
  const lab = $('#astSessionLabel'); if (lab) lab.textContent = '';
  $('#chatInput').value = '';
  $('#chatInput').focus();
}

// ------------------------------------------------------------------ 历史 prompt 回填
let PROMPT_ITEMS = [];

/** 拉取「跨会话最近的用户 prompt」，渲染到浮层列表。 */
async function astLoadPrompts() {
  const list = $('#promptHistList');
  try {
    const r = await get('/api/assistant/prompts?limit=40');
    if (!r.ok) { list.innerHTML = '<div class="empty">' + esc(r.error || '加载失败') + '</div>'; return; }
    const ps = r.prompts || [];
    PROMPT_ITEMS = ps;
    if (!ps.length) { list.innerHTML = '<div class="empty">暂无历史 prompt</div>'; return; }
    list.innerHTML = ps.map((p, i) =>
      '<div class="prompt-item" data-idx="' + i + '" title="' + esc(p.text) + '">' +
        '<span class="prompt-text">' + esc(p.text) + '</span>' +
        '<span class="prompt-time">' + esc(p.time || '') + '</span>' +
      '</div>').join('');
    list.querySelectorAll('.prompt-item').forEach(it => {
      it.onclick = () => {
        const p = PROMPT_ITEMS[+it.dataset.idx];
        if (p) { $('#chatInput').value = p.text; $('#chatInput').focus(); }
        togglePromptPop(false);
      };
    });
  } catch (e) {
    list.innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>';
  }
}

/** 切换「历史 prompt」浮层；show 省略时取反。 */
function togglePromptPop(show) {
  const pop = $('#promptHistPop');
  if (!pop) return;
  const willShow = (show === undefined) ? pop.classList.contains('hidden') : show;
  if (willShow) { astLoadPrompts(); pop.classList.remove('hidden'); }
  else { pop.classList.add('hidden'); }
}

// ------------------------------------------------------------------ 助手模型选择
// 仅列「实测可直连」的模型（2026-09-03 token.sensenova.cn 实测）：
//   sensenova-6.8-flash-lite → 返回无 content 字段（reasoning 结构）+ 极慢；
//   sensenova-6.7-flash-lite → HTTP 404（平台无该 chat 路由）；
//   kimi-k3                  → temperature 只允许 1（传 0.3 必 400）且当前 TPM 限流。
// 以上若留在列表，选中后会失败并被兜底链静默降级成 deepseek-v4-flash（即"怎么选都没用"），故剔除。
const DEFAULT_LLM_MODEL = 'deepseek-v4-flash';  // 全局主模型出厂默认
const AST_MODELS = [
  'deepseek-v4-flash',
  'glm-5.2',
  'deepseek-v4-pro',
];

function renderAssistantModels() {
  // 选择条直接控制全局 llm.model
  const cur = (CFG && CFG.llm && CFG.llm.model) || DEFAULT_LLM_MODEL;
  const bar = document.getElementById('assistantModels');
  const note = document.getElementById('astModelNote');
  if (!bar) return;
  const md = (CFG && CFG.assistant && CFG.assistant.backend) || 'api';
  if (md === 'workbuddy') {
    // 桥接模式：模型由 WorkBuddy 决定，选择条隐藏
    bar.style.display = 'none';
    bar.innerHTML = '';
    if (note) note.textContent = '桥接模式：模型由 WorkBuddy 决定，此处不可选。';
    return;
  }
  // API 直连：下拉框选择模型（不铺满 7 个按钮）
  bar.style.display = '';
  const opts = AST_MODELS.map(m => {
    const sel = (m === cur) ? ' selected' : '';
    return `<option value="${esc(m)}"${sel}>${esc(m)}</option>`;
  }).join('');
  bar.innerHTML = `<select id="astModelSelect" class="model-select">${opts}</select>`;
  const sel = bar.querySelector('#astModelSelect');
  sel.onchange = () => selectAssistantModel(sel.value);
  if (note) note.textContent = '当前对话模型：' + cur + ' · 云端直连';
}

async function selectAssistantModel(id) {
  // 直接改全局 llm.model 为所选具体模型（空值时回落出厂默认 deepseek-v4-flash）
  const model = id || DEFAULT_LLM_MODEL;
  const res = await post('/api/config', { llm: { model }, assistant: { model: '' } });
  if (!res.ok) { alert('保存失败：' + (res.error || '未知')); return; }
  if (res.config) CFG = res.config;       // 同步最新配置
  renderAssistantModels();
}

function initAssistant() {
  if (!AST.inited) {
    AST.inited = true;
    astLoadCtx();
    astLoadHist();
    $('#chatInput').focus();
  }
}

$('#btnSend').onclick = () => { const v = $('#chatInput').value; $('#chatInput').value = ''; astSend(v); };
$('#chatInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const v = $('#chatInput').value; $('#chatInput').value = '';
    astSend(v);
  }
});
$('#btnNewChat').onclick = astNewChat;
$('#btnHist').onclick = () => { astLoadHist(); astLoadCtx(); };
$('#btnPromptHist').onclick = (e) => { e.stopPropagation(); togglePromptPop(); };
// 点击浮层以外区域时收起
document.addEventListener('click', (e) => {
  const pop = $('#promptHistPop');
  if (!pop || pop.classList.contains('hidden')) return;
  const btn = $('#btnPromptHist');
  if (pop.contains(e.target) || (btn && btn.contains(e.target))) return;
  togglePromptPop(false);
});


(async function init() {
  const r = await get('/api/config');
  if (r.ok) { CFG = r.config; applyCfg(r.config); }
  renderAssistantModels();
  await loadSettings();
  await loadOverview();
  await loadDataDates();
  await loadTxt();
  await loadWechat();
  // LLM 连通性自检（不阻塞）
  post('/api/llm/test', {}).then(t => {
    $('#llmDot').className = 'dot ' + (t.ok ? 'ok' : 'err');
    if (t.ok) {
      const label = (t.model || '').replace('workbuddy', 'WorkBuddy 桥接');
      $('#llmDot').title = t.message ? t.message : `后端就绪（${label}）`;
    } else {
      $('#llmDot').title = t.message || '不可用';
      $('#ovNote').innerHTML += `<div class="note warn"><b>模型后端不可用</b>：${esc(t.message)}。AI 精读会失败，下载/重建/抓取不受影响。</div>`;
    }
  });
  // 自动挂载正在运行的精读任务：打开页面（含右栏/侧栏）即显示进度条+日志
  autoWatchAnno();
  setInterval(autoWatchAnno, 3000);
})();
