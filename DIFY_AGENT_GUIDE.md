# Dify 智能体使用指南 — Ozon Data Terminal

> 这份文档面向"已经在 Dify 工作区装好 Ozon 工具"的智能体/运营人员。说明工具能做什么、什么场景该调哪个、参数怎么填、常见错误如何处理。

---

## 一、可用工具一览（按调用场景）

### 接入方式 A：MCP 集成（推荐）

适用：`Dify 工作室 → 工具 → MCP → 安装 MCP`，URL 为 `http://127.0.0.1:9002/mcp`。
装好后 Dify 自动 `tools/list`，LLM 直接看到 9 个工具：

| 场景 | 工具名 | 何时用 |
| --- | --- | --- |
| 不知道用什么类目，先探一下 | `ozon_list_categories` | 用户给了一个宽泛的关键词，要先摸清命中了哪些 Ozon 类目（带子） |
| 已知类目 ID，要具体商品 | `ozon_search_keyword` 或 `ozon_search_filtered` | 第一步已经探到合适类目，需要真实商品 |
| 不知道类目 ID，但用户明确说"服装/3C/家居" | `ozon_search_category` | 直接在指定一级类目下浏览 |
| 用户问某商品的具体参数/评价 | `ozon_product_info` | 给一个 Ozon SKU 数字 ID |
| 想知道现在 Ozon 上什么卖得好 | `ozon_bestsellers` | 用户问"热卖品/爆款" |
| 用户给了精确需求（关键词 + 价格区间 + 排序） | `ozon_search_filtered` | 一次到位：keyword + category + price + sort |
| 想知道某关键词的热度趋势 | `ozon_keyword_tendency` | 投放前的可行性评估 |
| 多轮对话中重复利用上一次结果 | `ozon_query_list` | 减少重复抓取，节省时间 |
| 确认某个类目下都有哪些子类目 | `ozon_get_category_info` | 给类目 ID 直接拿子类目树 |

### 接入方式 B：OpenAPI 自定义工具

适用：`Dify 工作室 → 工具 → 自定义工具 → OpenAPI Schema`，Schema URL 为 `https://yidong.dianleida.net:21997/openapi/dify.json`，鉴权 `Bearer TtKQ-HRk0-P-7_owAa9u9IKxp6cKfyLkwPj_tfjclpU`。
LLM 看到的是单接口 `POST /api/dify/search`，调用时手填一个 JSON body。

> A 更直观，B 更通用。如果只是搜索，差别不大；如果想精细控制步骤，用 A。

---

## 二、典型调用流程

### 场景 1：用户问"在 Ozon 上搜女装 dress，要求 1000-5000 ₽"

如果使用 **A 方式**：

```text
1) ozon_list_categories(keyword="dress", deep=true)
   → 得到 [Одежда(7500)/Женская одежда(7501), ...]

2) 智能体匹配：用户问"女装" → 7500.Одежда > 7501.Женская одежда → id=7501

3) ozon_search_filtered(
     keyword="dress",
     category="7501",
     price_min=1000,
     price_max=5000,
     sort="relevance"
   )
   → 返回具体商品列表
```

如果使用 **B 方式**：

```json
// 第 1 次：探类目
POST /api/dify/search
{
  "keywords": ["dress"],
  "pages": 1, "target": 5, "preview": 5,
  "deep_categories": true,
  "with_categories": true
}

// 第 2 次：锁定类目 + 价格 + 排序
POST /api/dify/search
{
  "keywords": ["dress"],
  "category": "7501",
  "price_min": 1000,
  "price_max": 5000,
  "sort": "relevance",
  "pages": 3, "target": 120, "preview": 120
}
```

### 场景 2：用户问"Ozon 上现在什么卖得好"

```text
ozon_bestsellers(preset="all", pages=1, target=100, preview=20)
→ 返回 100 件畅销商品的列表
```

### 场景 3：用户问"这个商品（SKU 1234567890）怎么样"

```text
ozon_product_info(sku="1234567890")
→ 返回该商品的 id / title / price / rating / reviews / link / main_image
```

---

## 三、参数速查

### MCP 工具通用参数

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `keyword` | str | 必填 | 中文会被自动翻译成俄语变体合并去重（如"外套" → куртка/пальто/верхняя одежда） |
| `pages` | int | 3 | 每个关键词变体最多采集页数（1-20） |
| `target` | int | 120 | 累计最大商品数（1-500） |
| `preview` | int | 120 | 实际返回的商品条数（≤ target） |
| `category` | str | 空 | Ozon 类目数字 ID 字符串（如 `"7500"`） |
| `price_min/max` | int | 空 | ₽ 价格区间（0-10 000 000），`max ≥ min` |
| `sort` | str | 空 | `price` / `price_desc` / `relevance` / `newest` |
| `deep` | bool | false | 是否再请求每个一级类目页拿子类目 |

### OpenAPI 工具参数

请求体同 MCP，但多包一层：

```json
{
  "keywords": ["dress", "女装"],   // 数组，1-10 个
  "pages": 3, "target": 120, "preview": 120,
  "category": "7501",
  "price_min": 1000, "price_max": 5000,
  "sort": "relevance",
  "with_categories": true,
  "deep_categories": true
}
```

---

## 四、响应字段约定

两种接入方式响应结构一致：

```json
{
  "keyword": "dress",
  "requested_pages": 3,
  "pages": 3,
  "unique": 92,        // 累计去重后商品数
  "returned": 92,      // 实际返回商品数（≤ preview）
  "items": [
    {
      "id": "2904459819",
      "title": "...",
      "price": "375 ₸ × 12 мес",
      "original_price": "10 024 ₸",
      "discount": "-55%",
      "rating": "4.8",
      "reviews": "6 005 отзывов",
      "stock": "590 шт осталось",
      "link": "/product/.../...",
      "main_image": "https://ir-20.ozonstatic.cn/...",
      "images": ["..."]
    }
  ],
  "categories": [
    {
      "id": "7500",
      "name": "Одежда",
      "level": 0,
      "url": "/category/.../",
      "subcategories": [
        { "id": "7501", "name": "Женская одежда", "level": 1, "url": "...", "parent_id": "7500" }
      ]
    }
  ]
}
```

### 关键字段说明

| 字段 | 含义 |
| --- | --- |
| `id` | Ozon 商品 SKU（数字字符串） |
| `price` | 现价（Ozon 默认显示分期），单次买价见 `original_price` |
| `rating` / `reviews` | 评分 / 评论数（数字字符串） |
| `stock` | 库存剩余文本（俄语 `осталось`、哈语 `kaldı` 等） |
| `link` | 相对路径，拼接 `https://www.ozon.kz` 即可打开 |
| `categories[].subcategories` | 仅当请求带 `deep=true`/`deep_categories=true` 时填充 |

---

## 五、错误码对照

| 状态码 | 含义 | 处理建议 |
| --- | --- | --- |
| 200 | 成功 | 正常解析 `items` / `categories` |
| 401 | Bearer 鉴权失败 | Dify 工具页重新粘贴密钥 `TtKQ-HRk0-P-7_owAa9u9IKxp6cKfyLkwPj_tfjclpU` |
| 409 | 后端未注入 Ozon Cookie | 打开 `picks.html` → "粘贴 Cookie Header" → 重新调用 |
| 422 | 参数越界（如 `pages` 超过 20） | 按错误体修正参数后重试 |
| 400 | Ozon 接口执行失败（可能触发风控） | 降低 `pages`/`target`，稍后重试 |
| 502/超时 | 后端 9001 不可达 | 检查本机服务进程，必要时重启 `tusou-start.ps1` |
| 403 | 容器/网关拦截 | Dify 容器到映射域名的 outbound 不通，检查网络/白名单 |

> MCP 工具返回的 `RuntimeError` 在响应里以 `error` 字段出现，含义同上。

---

## 六、智能体系统提示词模板（直接贴到 Dify）

### MCP 方式

```text
你是一个 Ozon 选品助手，已装好 MCP server `ozon-terminal`，可调用 9 个工具：
- ozon_list_categories(keyword, deep) — 探类目
- ozon_search_keyword(keyword, pages, target, preview, category, price_min/max, sort) — 关键词搜索
- ozon_search_category(category, sort, ...) — 类目浏览
- ozon_search_filtered(keyword, category, price_min/max, sort, ...) — 综合筛选
- ozon_get_category_info(category_id, with_subcategories) — 类目详情+子类目
- ozon_product_info(sku) — 单商品详情
- ozon_bestsellers(preset, pages, target, preview) — 畅销榜
- ozon_keyword_tendency(keyword) — 趋势估算
- ozon_query_list(limit) — 上次结果摘要

参数规范：
- keyword：必填。中文会自动扩展到俄语变体。
- pages：默认 3，需要更全用 5-10。
- target/preview：默认 120。
- category：Ozon 类目数字 ID（如 "7500"）。
- price_min/price_max：₽，max ≥ min。
- sort：price / price_desc / relevance / newest。

推荐两步流程：
1) 首次：ozon_list_categories(keyword="...", deep=true) → 拿到完整类目树。
2) 比对 categories[].name 与 subcategories[].name，挑出用户想要的类目 id，作为 ozon_search_filtered 的 category 参数，重新搜商品。

错误处理：
- 工具返回错误：让用户重新配置 Dify 鉴权（401）/ 提醒去 picks.html 注入 Ozon Cookie（409）/ 修正参数（400/422）。
- 超时/502：让用户重启本机服务。
```

### OpenAPI 方式

```text
你是一个 Ozon 选品助手，已装好自定义工具 `ozon_product_search`。
调用方式：POST /api/dify/search，鉴权头 Authorization: Bearer <密钥>。

参数：
- keywords：必填数组，1-10 个关键词。
- pages/target/preview：默认 3/120/120。
- category：Ozon 类目数字 ID。
- price_min/price_max：₽。
- sort：price / price_desc / relevance / newest。
- with_categories：默认 true，返回命中的类目列表。
- deep_categories：默认 false，开启后会再请求一级类目页把子类目填进 subcategories。

推荐两步流程：
1) 第一次：仅 1 个关键词，with_pages=1、target=5、preview=5、with_categories=true、deep_categories=true → 拿到类目树。
2) 第二次：把上一步返回的 categories[].name/subcategories[].name 跟用户意图比对，挑出 id，作为 category 参数，重新搜商品。

错误处理：401 让用户重贴密钥；409 提醒去 picks.html 注入 Cookie；422/400 修正参数或等待后重试。
```

---

## 七、自检命令（运营侧）

```powershell
# 1) 本机 FastAPI 后端（9001）
curl.exe -s http://127.0.0.1:9001/api/health
# 期望：{"ok":true,"cookie_ready":true,"cookie_count":12}

# 2) 映射域名（Dify 容器走这条）
curl.exe -s -L https://yidong.dianleida.net:21997/api/health

# 3) Dify 拉 OpenAPI Schema
curl.exe -s -L -H 'Authorization: Bearer TtKQ-HRk0-P-7_owAa9u9IKxp6cKfyLkwPj_tfjclpU' ^
  https://yidong.dianleida.net:21997/openapi/dify.json | Select-Object -First 5

# 4) 走 MCP 协议确认 9 个 tool（需要 Python + mcp 库）
python -c "
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    async with streamablehttp_client('http://127.0.0.1:9002/mcp') as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print('tools:', [t.name for t in tools.tools])

asyncio.run(main())
"

# 5) Dify 容器侧验证（如果在 Dify 容器内执行）
curl -v https://yidong.dianleida.net:21997/api/health 2>&1 | tail -20
```

---

## 八、运维要点

| 项 | 操作 |
| --- | --- |
| 启动 FastAPI 后端 | `python -m ozon_terminal serve --host 0.0.0.0 --port 9001` |
| 启动 MCP server | `python -m ozon_terminal.mcp_server --host 0.0.0.0 --port 9002` |
| 注入 Ozon Cookie | 打开 `picks.html` → "粘贴 Cookie Header" → 粘贴从浏览器开发者工具复制的内容 |
| 轮换 Dify 密钥 | 修改 `tusou-start.ps1` 默认值，重启 FastAPI |
| 升级/重启服务 | `Stop-Process -Id <pid> -Force; <启动命令>` |

### Cookie 失效

Cookie 默认在 SQLite 持久化，但 Ozon 会话通常几小时到几天过期。表现是搜索返回 `403` 或商品列表大幅缩水。处理：

1. 浏览器登录 Ozon
2. F12 → Application → Cookies → 复制整段 Cookie Header
3. `picks.html` 粘贴 → 提交
4. 不需要重启服务

### 服务挂了

```powershell
netstat -ano | Select-String ':9001.*LISTENING'
Get-Process python | Format-Table Id,StartTime
# 如果没看到9001，参照"运维要点"里的启动命令重启
```

---

## 九、限制与已知问题

| 能力 | 状态 | 备注 |
| --- | --- | --- |
| 多关键词串行搜索 | ✅ | 单次最多 10 个 |
| 中文→俄语关键词自动扩展 | ✅ | 自动合并去重 |
| 类目、价格、排序筛选 | ✅ | 见参数速查 |
| 返回命中类目 ID 与 URL | ✅ | `with_categories=true` |
| 拉取一级类目下的子类目 | ✅ | `deep=true` / `deep_categories=true` |
| Ozon 分页续采 | ✅ | 含 `nextPage` 与 `page=N` 兜底 |
| 结果乱码修复 | ✅ | UTF-8 + Latin-1 + 多次 mojibake 修复 |
| 销量 / 销售额字段 | ❌ | 需云启浏览器插件或卖家 API |
| 商品上架时间 | ⚠️ 部分 | 仅能通过评论时间戳近似反推 |
| 单类目超过 1000 条 | ❌ | Ozon 服务端硬限 1000，需按类目 × 指标切分 |

---

## 十、版本对应

| 文档 | 对应 commit | 时间 |
| --- | --- | --- |
| `DIFY_AGENT_GUIDE.md`（本文件） | 后续 commit | 2026-09-03 起 |
| `MCP_INTEGRATION.md` | `f5fd77a` | 2026-09-02 |
| `DIFY_INTEGRATION.md` | `f131cb9` | 2026-09-02 |
| `ozon_terminal.mcp_server` 9 个 tool | `f5fd77a` | 2026-09-02 |
| FastAPI `/api/dify/search` + deep_categories | `f131cb9` | 2026-09-02 |

任何时间发现行为变化，先看 git log 是否更新了后端代码，再检查 Dify 工具是否需要重新保存以加载新 schema。