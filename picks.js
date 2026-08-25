// Ozon 选品库：批量关键词任务工作台。
const $ = (s) => document.querySelector(s);
const API_BASE = 'https://yidong.dianleida.net:21997';
const state = { groups: [], cookieReady: false, cookieCount: 0, running: false, cancelRequested: false, pages: 3, target: 120 };

function apiUrl(path) { return `${API_BASE}${path}`; }
function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c])); }
function ozonUrl(link) { if (!link) return '#'; return link.startsWith('http') ? link : `https://www.ozon.kz${link}`; }
function setStatus(kind, text) { const bar = $('#statusBar'); bar.className = `status-bar ${kind}`; bar.textContent = text; }
function statusLabel(group) {
  if (group.status === 'pending') return '等待中';
  if (group.status === 'loading') return `搜索中 · 请求 ${group.requested_pages} 页`;
  if (group.status === 'cancelled') return '已停止';
  if (group.status === 'error') return '失败';
  return `已完成 · ${group.pages} / ${group.requested_pages} 页 · ${group.unique || group.items.length} 件`;
}
function taskHtml(group, index) {
  const done = group.status === 'done' ? 100 : group.status === 'loading' ? 48 : group.status === 'error' ? 100 : 0;
  const action = group.status === 'error' || group.status === 'cancelled'
    ? `<button class="task-action" data-retry="${index}">重试</button>`
    : group.status === 'done' ? '<span class="task-check">完成</span>' : '';
  return `<div class="task-row ${group.status}">
    <div class="task-main"><span class="task-dot"></span><strong>${esc(group.keyword)}</strong><span class="task-status">${esc(statusLabel(group))}</span></div>
    <div class="task-progress"><span style="width:${done}%"></span></div>
    <div class="task-foot"><span>${group.status === 'loading' ? '接口处理中，完成后立即展示结果' : group.error ? esc(group.error) : `${group.items.length || 0} 件已载入`}</span>${action}</div>
  </div>`;
}
function renderTaskBoard() {
  const board = $('#taskBoard');
  if (!state.groups.length) { board.hidden = true; return; }
  board.hidden = false;
  const completed = state.groups.filter((g) => g.status === 'done').length;
  const active = state.groups.find((g) => g.status === 'loading');
  $('#taskSummaryText').textContent = state.running ? (active ? `正在处理「${active.keyword}」` : '准备任务') : `批次${completed === state.groups.length ? '已完成' : '已停止'}`;
  $('#taskSummaryCount').textContent = `${completed} / ${state.groups.length} 完成`;
  $('#overallProgressBar').style.width = `${Math.round((completed / state.groups.length) * 100)}%`;
  $('#taskList').innerHTML = state.groups.map(taskHtml).join('');
  $('#taskList').querySelectorAll('[data-retry]').forEach((button) => {
    button.onclick = () => retryTask(Number(button.dataset.retry));
  });
}
function productCard(item) {
  const link = ozonUrl(item.link);
  return `<article class="product-card"><a class="product-image" href="${esc(link)}" target="_blank" rel="noopener" style="background-image:url('${esc(item.main_image || '')}')"></a><div class="product-body"><a class="product-title" href="${esc(link)}" target="_blank" rel="noopener">${esc(item.title || '无标题')}</a><div class="product-price">${esc(item.price || '-')} ${item.original_price ? `<del>${esc(item.original_price)}</del>` : ''}</div><div class="product-meta">★ ${esc(item.rating || '-')} · ${esc(item.reviews || '0')} 条评价</div></div></article>`;
}
function groupHtml(group, index) {
  const items = group.items || [];
  const preview = items.slice(0, 5);
  const more = items.length ? `<button class="more-btn" data-keyword="${esc(group.keyword)}">查看更多 <span>→</span></button>` : '';
  const retry = group.status === 'error' || group.status === 'cancelled' ? `<button class="more-btn retry-inline" data-retry="${index}">重试</button>` : '';
  return `<article class="keyword-group ${group.status}"><div class="group-head"><div class="group-keyword"><span class="group-mark"></span><h3>${esc(group.keyword)}</h3><span class="group-state">${esc(statusLabel(group))}</span></div><div class="group-actions">${retry}${more}</div></div>${group.error ? `<div class="group-error">${esc(group.error)}</div>` : ''}<div class="product-strip">${preview.length ? preview.map(productCard).join('') : `<div class="group-empty">${group.status === 'loading' ? '正在通过 Ozon 接口采集，结果返回后自动出现…' : group.status === 'pending' ? '排队等待中…' : group.status === 'cancelled' ? '此任务已停止，可点击重试。' : '暂无商品结果'}</div>`}</div></article>`;
}
function renderGroups() {
  const container = $('#groups');
  if (!state.groups.length) { container.className = 'groups empty'; container.textContent = '暂无结果'; return; }
  container.className = 'groups'; container.innerHTML = state.groups.map(groupHtml).join('');
  container.querySelectorAll('.more-btn[data-keyword]').forEach((button) => { button.onclick = () => openResults(button.dataset.keyword); });
  container.querySelectorAll('[data-retry]').forEach((button) => { button.onclick = () => retryTask(Number(button.dataset.retry)); });
  renderTaskBoard();
}
function openResults(keyword) {
  const group = state.groups.find((item) => item.keyword === keyword); if (!group) return;
  $('#dialogTitle').textContent = `“${group.keyword}” 的全部商品`;
  $('#dialogMeta').textContent = `已搜索 ${group.pages || 0} / ${group.requested_pages || 0} 页 · 去重 ${group.unique || group.items.length} 件 · 当前展示 ${group.items.length} 件`;
  $('#dialogGrid').innerHTML = (group.items || []).map(productCard).join('') || '<div class="group-empty">暂无结果</div>';
  $('#resultsDialog').showModal();
}
async function refreshHealth() {
  try {
    const response = await fetch(apiUrl('/api/health')); const health = await response.json();
    state.cookieReady = !!health.cookie_ready; state.cookieCount = Number(health.cookie_count || 0);
    $('#cookieDot').classList.toggle('on', state.cookieReady); $('#cookieText').textContent = state.cookieReady ? `已装载 ${state.cookieCount} 项 Cookie` : 'Cookie 未上传';
    $('#hint').textContent = state.cookieReady ? `Cookie 已保存。当前接口基址：${API_BASE}` : '首次使用请先粘贴 Ozon Cookie Header。';
    if (!state.running) setStatus(state.cookieReady ? 'ready' : 'warning', state.cookieReady ? `Cookie 已就绪，当前已装载 ${state.cookieCount} 项，可直接搜索。` : 'Cookie 还未就绪，请先上传 Cookie。');
  } catch (_) { state.cookieReady = false; $('#cookieText').textContent = '服务未连接'; if (!state.running) setStatus('error', '搜索服务未连接，请检查映射服务。'); }
}
async function searchKeyword(group) {
  group.status = 'loading'; group.requested_pages = state.pages; group.error = ''; renderGroups();
  try {
    const response = await fetch(apiUrl('/api/search'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ keyword: group.keyword, pages: state.pages, target: state.target, preview: state.target }) });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json(); group.items = data.items || []; group.requested_pages = data.requested_pages || state.pages; group.pages = data.pages || 0; group.unique = data.unique || group.items.length; group.status = 'done';
  } catch (error) { group.status = state.cancelRequested ? 'cancelled' : 'error'; group.error = state.cancelRequested ? '已由用户停止' : (error.message || '搜索失败'); }
  renderGroups();
}
async function retryTask(index) {
  if (state.running || !state.cookieReady) return;
  state.running = true; state.cancelRequested = false; $('#searchBtn').disabled = true; $('#cancelBtn').disabled = false;
  await searchKeyword(state.groups[index]);
  state.running = false; $('#searchBtn').disabled = false; $('#cancelBtn').disabled = true;
  const success = state.groups.filter((g) => g.status === 'done').length; setStatus(success === state.groups.length ? 'ready' : 'warning', `任务更新完成：${success} / ${state.groups.length} 个关键词成功。`);
}
async function runBatchSearch() {
  if (state.running) return;
  const keywords = $('#keywords').value.split(/\r?\n|,|，/).map((item) => item.trim()).filter(Boolean);
  const uniqueKeywords = [...new Set(keywords)]; state.pages = Math.max(1, Math.min(100, Number($('#pages').value || 3))); state.target = Math.max(5, Math.min(2000, Number($('#target').value || 120)));
  if (!uniqueKeywords.length) return alert('请至少输入一个关键词，每行一个。');
  if (!state.cookieReady) { setStatus('warning', '请先上传 Cookie，再开始搜索。'); $('#cookieDialog').showModal(); return; }
  state.running = true; state.cancelRequested = false; $('#searchBtn').disabled = true; $('#cancelBtn').disabled = false;
  state.groups = uniqueKeywords.map((keyword) => ({ keyword, items: [], status: 'pending', requested_pages: state.pages, pages: 0 }));
  $('#resultTitle').textContent = `批量搜索 ${uniqueKeywords.length} 个关键词`; $('#resultMeta').textContent = `${state.pages} 页 / 关键词 · 每组默认展示 5 个 · 串行降低风控`; renderGroups();
  for (let index = 0; index < state.groups.length; index += 1) {
    if (state.cancelRequested) { state.groups.slice(index).forEach((g) => { g.status = 'cancelled'; g.error = '已由用户停止'; }); renderGroups(); break; }
    setStatus('loading', `正在搜索 ${index + 1} / ${state.groups.length} 个关键词：${state.groups[index].keyword}`);
    await searchKeyword(state.groups[index]);
  }
  state.running = false; $('#searchBtn').disabled = false; $('#cancelBtn').disabled = true;
  const success = state.groups.filter((group) => group.status === 'done').length;
  setStatus(success === state.groups.length ? 'ready' : 'warning', state.cancelRequested ? `批次已停止：${success} / ${state.groups.length} 个关键词完成。` : `批量搜索完成：${success} / ${state.groups.length} 个关键词成功。`); renderTaskBoard();
}
const cookieDialog = $('#cookieDialog');
$('#pasteBtn').onclick = () => cookieDialog.showModal();
$('#uploadBtn').onclick = async (event) => { event.preventDefault(); const header = $('#cookieTextarea').value.trim(); if (!header) return alert('请粘贴 Cookie'); const response = await fetch(apiUrl('/api/cookies/header'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ header, domain: '.ozon.kz' }) }); if (!response.ok) return alert(`上传失败：${await response.text()}`); $('#cookieTextarea').value = ''; cookieDialog.close(); await refreshHealth(); };
$('#searchBtn').onclick = runBatchSearch;
$('#cancelBtn').onclick = () => { if (state.running) { state.cancelRequested = true; setStatus('warning', '正在停止当前请求，完成后结束批次…'); } };
$('#closeResults').onclick = () => $('#resultsDialog').close(); $('#resultsDialog').addEventListener('click', (event) => { if (event.target === $('#resultsDialog')) $('#resultsDialog').close(); });
refreshHealth(); setInterval(refreshHealth, 5000);