// 选品库页面：调用本地后端 /api/search 拉取数据，按筛选/排序/分页展示。
const $ = (s) => document.querySelector(s);

const state = {
  keyword: '',
  items: [],
  filtered: [],
  page: 1,
  pageSize: 24,
  sort: '',
  minPrice: null,
  maxPrice: null,
  minRating: null,
  category: '',
  cookieReady: false,
  cookieCount: 0,
};

function setStatus(kind, text) {
  const bar = $('#statusBar');
  if (!bar) return;
  bar.className = `status-bar ${kind}`;
  bar.textContent = text;
}

async function refreshHealth() {
  try {
    const r = await fetch('/api/health');
    const h = await r.json();
    state.cookieReady = !!h.cookie_ready;
    state.cookieCount = Number(h.cookie_count || 0);
    $('#cookieDot').classList.toggle('on', state.cookieReady);
    $('#cookieText').textContent = state.cookieReady
      ? `已装载 ${state.cookieCount} 项 Cookie`
      : 'Cookie 未上传';
    $('#hint').textContent = state.cookieReady
      ? 'Cookie 已保存到本地 SQLite，服务重启后会自动恢复。'
      : '首次使用请先粘贴 Ozon Cookie Header，保存后下次启动会自动恢复。';
    setStatus(
      state.cookieReady ? 'ready' : 'warning',
      state.cookieReady
        ? `Cookie 已就绪，当前已装载 ${state.cookieCount} 项，可直接搜索。`
        : 'Cookie 还未就绪，请先粘贴 Ozon Cookie Header。'
    );
  } catch (_) {
    state.cookieReady = false;
    state.cookieCount = 0;
    $('#cookieText').textContent = '服务未连接';
    setStatus('error', '本地服务未连接，请先启动 9001 端口服务。');
  }
}

function applyFilters() {
  let arr = state.items.slice();
  if (state.minPrice != null) arr = arr.filter((x) => parsePrice(x.price) >= state.minPrice);
  if (state.maxPrice != null) arr = arr.filter((x) => parsePrice(x.price) <= state.maxPrice);
  if (state.minRating != null) arr = arr.filter((x) => parseFloat(x.rating || '0') >= state.minRating);
  if (state.category) arr = arr.filter((x) => (x.title || '').toLowerCase().includes(state.category.toLowerCase()) || true);
  switch (state.sort) {
    case 'price': arr.sort((a, b) => parsePrice(a.price) - parsePrice(b.price)); break;
    case 'price_desc': arr.sort((a, b) => parsePrice(b.price) - parsePrice(a.price)); break;
    case 'rating': arr.sort((a, b) => parseFloat(b.rating || '0') - parseFloat(a.rating || '0')); break;
    case 'reviews': arr.sort((a, b) => parseInt((b.reviews || '0').replace(/\D/g, ''), 10) - parseInt((a.reviews || '0').replace(/\D/g, ''), 10)); break;
  }
  state.filtered = arr;
}

function parsePrice(s) {
  if (!s) return 0;
  const m = s.replace(/\s/g, '').match(/(\d[\d,]*)/);
  return m ? parseFloat(m[1].replace(/,/g, '')) : 0;
}

function render() {
  applyFilters();
  const total = state.filtered.length;
  const start = (state.page - 1) * state.pageSize;
  const rows = state.filtered.slice(start, start + state.pageSize);
  const grid = $('#grid');
  if (!rows.length) {
    grid.className = 'grid empty';
    grid.textContent = state.keyword ? '当前筛选条件下无结果' : '暂无结果';
  } else {
    grid.className = 'grid';
    grid.innerHTML = rows.map(cardHtml).join('');
  }
  $('#resultMeta').innerHTML = state.items.length
    ? `共 <b>${state.items.length}</b> 件 · 筛选 <b>${total}</b> 件`
    : '';
  const pages = Math.max(1, Math.ceil(total / state.pageSize));
  if (state.page > pages) state.page = pages;
  $('#pageInfo').textContent = `${state.page} / ${pages}`;
  $('#prevBtn').disabled = state.page <= 1;
  $('#nextBtn').disabled = state.page >= pages;
}

function cardHtml(item) {
  const title = item.title || '(无标题)';
  const link = item.link ? `https://www.ozon.kz${item.link}` : '#';
  return `<article class="card">
    <a class="img" href="${esc(link)}" target="_blank" rel="noopener" style="background-image:url('${esc(item.main_image || '')}')"></a>
    <div class="body">
      <a class="title" href="${esc(link)}" target="_blank" rel="noopener">${esc(title)}</a>
      <div class="row">
        <span class="price">${esc(item.price || '')}</span>
        ${item.original_price ? `<span class="strike">${esc(item.original_price)}</span>` : ''}
        ${item.discount ? `<span class="discount">${esc(item.discount)}</span>` : ''}
      </div>
      <div class="meta">
        <span class="rating">★ ${esc(item.rating || '-')} · ${esc(item.reviews || '0')}</span>
        <span class="stock">${esc(item.stock || '')}</span>
      </div>
    </div>
  </article>`;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

async function runSearch() {
  state.keyword = $('#kw').value.trim();
  state.sort = $('#sort').value;
  state.category = $('#category').value;
  state.minPrice = $('#minPrice').value ? parseFloat($('#minPrice').value) : null;
  state.maxPrice = $('#maxPrice').value ? parseFloat($('#maxPrice').value) : null;
  state.minRating = $('#minRating').value ? parseFloat($('#minRating').value) : null;
  state.pageSize = Math.max(8, Math.min(60, parseInt($('#pageSize').value || '24', 10)));
  state.page = 1;

  if (!state.keyword) {
    alert('请输入关键词');
    return;
  }
  if (!state.cookieReady) {
    setStatus('warning', '当前还没有可用 Cookie，请先粘贴后再搜索。');
    dlg.showModal();
    return;
  }

  $('#resultTitle').textContent = `“${state.keyword}” 的搜索结果`;
  $('#grid').className = 'grid empty';
  $('#grid').textContent = '正在通过接口采集…';
  setStatus('loading', `正在搜索 “${state.keyword}” ...`);

  try {
    const r = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keyword: state.keyword, target: 120, preview: 120 })
    });
    if (!r.ok) {
      const t = await r.text();
      $('#grid').className = 'grid empty';
      $('#grid').textContent = '采集失败：' + t;
      setStatus('error', '采集失败，请检查 Cookie 是否失效后重试。');
      return;
    }
    const data = await r.json();
    state.items = data.items || [];
    render();
    setStatus('ready', `搜索完成，返回 ${state.items.length} 条结果。`);
  } catch (err) {
    $('#grid').className = 'grid empty';
    $('#grid').textContent = '请求出错：' + err.message;
    setStatus('error', '请求出错，请确认本地服务仍在运行。');
  }
}

document.getElementById('searchBtn').onclick = runSearch;
document.getElementById('prevBtn').onclick = () => {
  if (state.page > 1) {
    state.page--;
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
};
document.getElementById('nextBtn').onclick = () => {
  const pages = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
  if (state.page < pages) {
    state.page++;
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
};
document.getElementById('kw').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') runSearch();
});

const dlg = document.getElementById('cookieDialog');
document.getElementById('pasteBtn').onclick = () => dlg.showModal();
document.getElementById('uploadBtn').onclick = async (e) => {
  e.preventDefault();
  const text = document.getElementById('cookieTextarea').value.trim();
  if (!text) {
    alert('请粘贴 Cookie');
    return;
  }
  const r = await fetch('/api/cookies/header', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ header: text, domain: '.ozon.kz' })
  });
  if (r.ok) {
    document.getElementById('cookieTextarea').value = '';
    dlg.close();
    await refreshHealth();
    setStatus('ready', 'Cookie 已保存到本地，后续重启服务也会自动恢复。');
  } else {
    alert('上传失败：' + await r.text());
    setStatus('error', 'Cookie 上传失败，请检查粘贴内容。');
  }
};

refreshHealth();
setInterval(refreshHealth, 5000);
