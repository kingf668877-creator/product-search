// Ozon 选品库：批量关键词搜索与按关键词分组展示。
const $ = (s) => document.querySelector(s);
const API_BASE = 'https://yidong.dianleida.net:21997';
const state = { groups: [], cookieReady: false, cookieCount: 0, running: false };

function apiUrl(path) { return `${API_BASE}${path}`; }
function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
}
function ozonUrl(link) {
  if (!link) return '#';
  return link.startsWith('http') ? link : `https://www.ozon.kz${link}`;
}
function setStatus(kind, text) {
  const bar = $('#statusBar');
  bar.className = `status-bar ${kind}`;
  bar.textContent = text;
}

async function refreshHealth() {
  try {
    const response = await fetch(apiUrl('/api/health'));
    const health = await response.json();
    state.cookieReady = !!health.cookie_ready;
    state.cookieCount = Number(health.cookie_count || 0);
    $('#cookieDot').classList.toggle('on', state.cookieReady);
    $('#cookieText').textContent = state.cookieReady ? `已装载 ${state.cookieCount} 项 Cookie` : 'Cookie 未上传';
    $('#hint').textContent = state.cookieReady
      ? `Cookie 已保存。当前接口基址：${API_BASE}`
      : '首次使用请先粘贴 Ozon Cookie Header。';
    setStatus(state.cookieReady ? 'ready' : 'warning', state.cookieReady
      ? `Cookie 已就绪，当前已装载 ${state.cookieCount} 项，可直接搜索。`
      : 'Cookie 还未就绪，请先上传 Cookie。');
  } catch (_) {
    state.cookieReady = false;
    $('#cookieText').textContent = '服务未连接';
    setStatus('error', '本地服务未连接，请先启动 9001 端口服务。');
  }
}

function productCard(item) {
  const link = ozonUrl(item.link);
  return `<article class="product-card">
    <a class="product-image" href="${esc(link)}" target="_blank" rel="noopener" style="background-image:url('${esc(item.main_image || '')}')"></a>
    <div class="product-body">
      <a class="product-title" href="${esc(link)}" target="_blank" rel="noopener">${esc(item.title || '无标题')}</a>
      <div class="product-price">${esc(item.price || '-')} ${item.original_price ? `<del>${esc(item.original_price)}</del>` : ''}</div>
      <div class="product-meta">★ ${esc(item.rating || '-')} · ${esc(item.reviews || '0')} 条评价</div>
    </div>
  </article>`;
}

function groupHtml(group) {
  const items = group.items || [];
  const preview = items.slice(0, 5);
  const stateText = group.status === 'loading' ? '搜索中' : group.status === 'error' ? '失败' : `请求 ${group.requested_pages || 0} 页 · 实际 ${group.pages || 0} 页 · ${group.unique || items.length} 件`;
  return `<article class="keyword-group ${group.status}">
    <div class="group-head">
      <div class="group-keyword"><span class="group-mark"></span><h3>${esc(group.keyword)}</h3><span class="group-state">${esc(stateText)}</span></div>
      <button class="more-btn" data-keyword="${esc(group.keyword)}" ${items.length ? '' : 'disabled'}>查看更多 <span>→</span></button>
    </div>
    ${group.error ? `<div class="group-error">${esc(group.error)}</div>` : ''}
    <div class="product-strip">${preview.length ? preview.map(productCard).join('') : `<div class="group-empty">${group.status === 'loading' ? '正在通过接口采集…' : '暂无商品结果'}</div>`}</div>
  </article>`;
}

function renderGroups() {
  const container = $('#groups');
  if (!state.groups.length) {
    container.className = 'groups empty';
    container.textContent = '暂无结果';
    return;
  }
  container.className = 'groups';
  container.innerHTML = state.groups.map(groupHtml).join('');
  container.querySelectorAll('.more-btn').forEach((button) => {
    button.onclick = () => openResults(button.dataset.keyword);
  });
}

function openResults(keyword) {
  const group = state.groups.find((item) => item.keyword === keyword);
  if (!group) return;
  $('#dialogTitle').textContent = `“${group.keyword}” 的全部商品`;
  $('#dialogMeta').textContent = `已搜索 ${group.pages || 0} 页 · 去重 ${group.unique || group.items.length} 件 · 当前展示 ${group.items.length} 件`;
  $('#dialogGrid').innerHTML = (group.items || []).map(productCard).join('') || '<div class="group-empty">暂无结果</div>';
  $('#resultsDialog').showModal();
}

async function searchKeyword(group, pages, target) {
  group.status = 'loading';
  renderGroups();
  try {
    const response = await fetch(apiUrl('/api/search'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keyword: group.keyword, pages, target, preview: target })
    });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    group.items = data.items || [];
    group.requested_pages = data.requested_pages || pages;
    group.pages = data.pages || 0;
    group.unique = data.unique || group.items.length;
    group.status = 'done';
  } catch (error) {
    group.status = 'error';
    group.error = error.message || '搜索失败';
  }
  renderGroups();
}

async function runBatchSearch() {
  if (state.running) return;
  const keywords = $('#keywords').value.split(/\r?\n|,|，/).map((item) => item.trim()).filter(Boolean);
  const uniqueKeywords = [...new Set(keywords)];
  const pages = Math.max(1, Math.min(100, Number($('#pages').value || 3)));
  const target = Math.max(5, Math.min(2000, Number($('#target').value || 120)));
  if (!uniqueKeywords.length) return alert('请至少输入一个关键词，每行一个。');
  if (!state.cookieReady) { setStatus('warning', '请先上传 Cookie，再开始搜索。'); $('#cookieDialog').showModal(); return; }

  state.running = true;
  $('#searchBtn').disabled = true;
  state.groups = uniqueKeywords.map((keyword) => ({ keyword, items: [], status: 'pending' }));
  $('#resultTitle').textContent = `批量搜索 ${uniqueKeywords.length} 个关键词`;
  $('#resultMeta').textContent = `${pages} 页 / 关键词 · 每组默认展示 5 个`;
  renderGroups();
  setStatus('loading', `正在搜索 0 / ${uniqueKeywords.length} 个关键词…`);

  for (let index = 0; index < state.groups.length; index += 1) {
    await searchKeyword(state.groups[index], pages, target);
    setStatus('loading', `正在搜索 ${index + 1} / ${state.groups.length} 个关键词…`);
  }
  state.running = false;
  $('#searchBtn').disabled = false;
  const success = state.groups.filter((group) => group.status === 'done').length;
  setStatus(success === state.groups.length ? 'ready' : 'warning', `批量搜索完成：${success} / ${state.groups.length} 个关键词成功。`);
}

const cookieDialog = $('#cookieDialog');
$('#pasteBtn').onclick = () => cookieDialog.showModal();
$('#uploadBtn').onclick = async (event) => {
  event.preventDefault();
  const header = $('#cookieTextarea').value.trim();
  if (!header) return alert('请粘贴 Cookie');
  const response = await fetch(apiUrl('/api/cookies/header'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ header, domain: '.ozon.kz' })
  });
  if (!response.ok) return alert(`上传失败：${await response.text()}`);
  $('#cookieTextarea').value = '';
  cookieDialog.close();
  await refreshHealth();
};
$('#searchBtn').onclick = runBatchSearch;
$('#closeResults').onclick = () => $('#resultsDialog').close();
$('#resultsDialog').addEventListener('click', (event) => { if (event.target === $('#resultsDialog')) $('#resultsDialog').close(); });

refreshHealth();
setInterval(refreshHealth, 5000);
