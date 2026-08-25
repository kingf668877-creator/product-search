const $=s=>document.querySelector(s);const api=async(url,opt={})=>{const r=await fetch(url,opt);let body;try{body=await r.json()}catch{body={detail:await r.text()}}if(!r.ok)throw Error(body.detail||`HTTP ${r.status}`);return body};
function toast(msg){const n=$('#toast');n.textContent=msg;n.classList.add('show');clearTimeout(n.t);n.t=setTimeout(()=>n.classList.remove('show'),3200)}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function statusName(s){return({pending:'等待',running:'运行',pausing:'暂停中',paused:'已暂停',cancelling:'取消中',cancelled:'已取消',completed:'完成',failed:'失败'})[s]||s}
async function refresh(){try{const [h,jobs]=await Promise.all([api('/api/health'),api('/api/jobs')]);$('#cookieDot').classList.toggle('on',h.cookie_ready);$('#cookieText').textContent=h.cookie_ready?`已装载 ${h.cookie_count} 项`:'未连接';$('#jobCount').textContent=String(jobs.length).padStart(2,'0');$('#itemCount').textContent=String(jobs.reduce((a,j)=>a+j.items,0)).padStart(6,'0');$('#jobs').innerHTML=jobs.length?jobs.map((j,i)=>`<article class="job"><span>${String(i+1).padStart(2,'0')}</span><div><span class="job-id">${esc(j.id)}</span><div class="endpoint" title="${esc(j.endpoint)}">${esc(j.endpoint)}</div></div><div class="stat">PAGES<b>${j.pages}</b></div><div class="stat">ITEMS<b>${j.items}</b></div><div class="status ${j.status}" title="${esc(j.error||'')}">${statusName(j.status)}</div><div class="controls">${['paused','failed','pending'].includes(j.status)?`<button onclick="act('${j.id}','resume')">继续</button>`:''}${['running','pending'].includes(j.status)?`<button onclick="act('${j.id}','pause')">暂停</button>`:''}${!['completed','cancelled'].includes(j.status)?`<button onclick="act('${j.id}','cancel')">取消</button>`:''}<button onclick="location.href='/api/jobs/${j.id}/export.csv'">CSV</button><button onclick="location.href='/api/jobs/${j.id}/export.json'">JSON</button></div></article>`).join(''):'<div class="empty">等待作业输入<span>NO ACTIVE TELEMETRY</span></div>'}catch(e){toast(e.message)}}
window.act=async(id,action)=>{try{await api(`/api/jobs/${id}/${action}`,{method:'POST'});await refresh()}catch(e){toast(e.message)}};
async function uploadFromBrowser(){
  return new Promise((resolve,reject)=>{
    const iframe=document.createElement('iframe');
    iframe.style.display='none';
    iframe.src='https://www.ozon.kz/';
    iframe.onload=()=>{
      try{
        const raw=iframe.contentDocument?iframe.contentDocument.cookie:iframe.contentWindow?iframe.contentWindow.document.cookie:'';
        iframe.remove();
        if(!raw)return reject(new Error('未读取到 Ozon Cookie：请先在此浏览器中登录 Ozon'));
        const cookies=raw.split(';').map(s=>{const i=s.indexOf('=');return i<0?{name:s.trim(),value:''}:{name:s.slice(0,i).trim(),value:s.slice(i+1).trim()}}).filter(c=>c.name);
        if(!cookies.length)return reject(new Error('当前浏览器未检测到 Ozon Cookie'));
        resolve(api('/api/cookies/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain:'.ozon.kz',cookies})}));
      }catch(err){iframe.remove();reject(err)}
    };
    iframe.onerror=()=>{iframe.remove();reject(new Error('无法访问 Ozon 站点，请检查网络或浏览器安全策略'))};
    document.body.appendChild(iframe);
    setTimeout(()=>{try{iframe.contentDocument||iframe.contentWindow}else{iframe.remove();reject(new Error('加载 Ozon 站点超时'))}},8000);
  });
}
async function uploadFromHeader(){
  const text=document.getElementById('cookiePaste').value.trim();
  if(!text)throw new Error('请粘贴 Cookie Header');
  return api('/api/cookies/header',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({header:text,domain:'.ozon.kz'})});
}
$('#cookieBtn').onclick=async()=>{try{const r=await uploadFromBrowser();toast(`已从浏览器上传 ${r.count} 项 Cookie`);refresh()}catch(e){toast(e.message)}};
$('#pasteBtn').onclick=async()=>{try{const r=await uploadFromHeader();toast(`已上传 ${r.count} 项 Cookie`);refresh()}catch(e){toast(e.message)}};
$('#clearBtn').onclick=async()=>{await api('/api/cookies',{method:'DELETE'});toast('内存凭据已清除');refresh()};$('#refresh').onclick=refresh;
$('#jobForm').onsubmit=async e=>{e.preventDefault();let request;try{request=JSON.parse($('#request').value)}catch{toast('REQUEST JSON 格式错误');return}try{await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint:$('#endpoint').value,method:$('#method').value,request})});toast('采集任务已启动');refresh()}catch(err){toast(err.message)}};
function renderResults(data){
  const sum=$('#searchSummary');const box=$('#results');
  sum.classList.remove('hidden');
  box.classList.remove('hidden');
  sum.innerHTML=`关键词 <b>${esc(data.keyword)}</b> · 翻页 <b>${data.pages}</b> · 唯一商品 <b>${data.unique}</b> · 本次返回 <b>${data.returned}</b>`;
  if(!data.items||!data.items.length){box.innerHTML='<div class="empty">未找到商品<span>NO MATCH</span></div>';return}
  const rows=data.items.map((it,i)=>`<tr><td>${i+1}</td><td><a href="https://www.ozon.kz${esc(it.link||'')}" target="_blank" rel="noopener">${esc(it.title||'(无标题)')}</a></td><td>${esc(it.price||'')}</td><td>${esc(it.original_price||'')}</td><td>${esc(it.discount||'')}</td><td>${esc(it.rating||'')}</td><td>${esc(it.reviews||'')}</td><td><img src="${esc(it.main_image||'')}" alt="" loading="lazy"></td></tr>`).join('');
  box.innerHTML=`<table><thead><tr><th>#</th><th>标题</th><th>现价</th><th>原价</th><th>折扣</th><th>评分</th><th>评价</th><th>主图</th></tr></thead><tbody>${rows}</tbody></table>`;
}
$('#searchForm').onsubmit=async e=>{e.preventDefault();const kw=$('#kw').value.trim();if(!kw){toast('请输入关键词');return}const target=Number($('#target').value)||2000;const preview=Number($('#preview').value)||120;$('#searchSummary').classList.remove('hidden');$('#searchSummary').textContent='正在顺序翻页采集，请耐心等待…';$('#results').classList.add('hidden');try{const data=await api('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keyword:kw,target,preview})});renderResults(data)}catch(err){$('#searchSummary').textContent='采集失败：'+err.message}};
setInterval(()=>{$('#clock').textContent=new Date().toLocaleTimeString('zh-CN',{hour12:false})+' / LOCAL'},1000);setInterval(refresh,2000);refresh();
