# Ozon Data Terminal × Dify 接入指南

## 一、接入架构

```text
Dify 智能体（Agent / Workflow）
   ↓ OpenAPI 自定义工具 ozon_product_search
   ↓  HTTPS POST /api/dify/search
   ↓  Authorization: Bearer <OZON_DIFY_API_KEY>
FastAPI 后端 (https://yidong.dianleida.net:21997 → 本地 :9001)
   ↓  Cookie 复用（已在网页端 picks.html 注入）
Ozon 搜索入口 API (entrypoint-api.bx/page/json/v2)
   ↓  分页、关键词扩展、乱码修复、类目回填（含二级类目）
结果回传到 Dify 智能体
```

## 二、当前可用接入点

| 项目             | 值                                             |
| -------------- | --------------------------------------------- |
| 后端监听           | `0.0.0.0:9001`（本机）                            |
| 映射域名           | `https://yidong.dianleida.net:21997`          |
| 搜索接口           | `POST /api/dify/search`                       |
| OpenAPI Schema | `GET /openapi/dify.json`                      |
| 鉴权请求头          | `Authorization: Bearer <OZON_DIFY_API_KEY>`   |
| 当前密钥           | `TtKQ-HRk0-P-7_owAa9u9IKxp6cKfyLkwPj_tfjclpU` |
| 鉴权实现           | 环境变量 `OZON_DIFY_API_KEY`，未配置则全部返回 401         |

> 密钥目前保存在桌面上的"一键启动图搜.bat → tusou-start.ps1"中，开机自启时会自动注入环境变量。

## 三、Dify 后台接入步骤

### 1. 创建自定义工具

1. 登录 Dify → 进入目标工作区。
2. 顶部菜单 `工具` → `自定义工具`。
3. 点击 `创建自定义工具`，类型选择 `OpenAPI Schema`。

### 2. 填写工具元数据

| 字段   | 值                                                 |
| ---- | ------------------------------------------------- |
| 工具名称 | `ozon_product_search`                             |
| 工具描述 | 使用登录态 Ozon 账号进行关键词搜索，返回商品标题、价格、评分、评价数、商品链接、主图等字段。 |

### 3. 导入 OpenAPI Schema

Schema 来源选择 `URL`，粘贴：

```text
https://yidong.dianleida.net:21997/openapi/dify.json
```

- Dify 拉取后会解析出 `POST /api/dify/search`。

- 如果在内网调试，可改为 `http://127.0.0.1:9001/openapi/dify.json`。

- 注意：该 URL 同样需要 Bearer Token，Dify 导入时会自带鉴权字段；但手动 `curl` 时要补 `Authorization` 头。

### 4. 配置鉴权

| 字段    | 值                                             |
| ----- | --------------------------------------------- |
| 鉴权方式  | `Bearer`                                      |
| Token | `TtKQ-HRk0-P-7_owAa9u9IKxp6cKfyLkwPj_tfjclpU` |

### 5. 保存并校验

保存工具后，在工具详情页测试一次调用：

```json
{
  "keywords": ["外套"],
  "pages": 1,
  "target": 5,
  "preview": 5
}
```

期望返回 200，且 `results[0].keyword == "外套"`。

## 四、参数与响应契约

### 请求

```json
{
  "keywords": ["dress"],
  "pages": 3,
  "target": 120,
  "preview": 120,
  "category": "7500",
  "price_min": 1000,
  "price_max": 5000,
  "sort": "price",
  "with_categories": true,
  "deep_categories": false
}
```

| 参数                | 必填 | 范围                                              | 默认    | 说明                                                                                                                                   |
| ----------------- | -- | ----------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `keywords`        | 是  | 1-10 个，每个长度 ≤120                                | -     | 串行执行，原词 + 中文/俄语扩展词合并去重                                                                                                               |
| `pages`           | 否  | 1-20                                            | 3     | 每个关键词最多采集页数                                                                                                                          |
| `target`          | 否  | 1-500                                           | 120   | 每个关键词最大返回商品数                                                                                                                         |
| `preview`         | 否  | 1-500，不大于 target                                | 120   | 响应中保留的商品数                                                                                                                            |
| `category`        | 否  | Ozon 类目数字 ID（如 `"7500"`）                        | 空     | 命中后会写入 `/search/?category=...`                                                                                                       |
| `price_min`       | 否  | 0-10 000 000（₽）                                 | 空     | 最低价格；对应 Ozon `minPrice`                                                                                                              |
| `price_max`       | 否  | 0-10 000 000（₽），需 ≥ `price_min`                 | 空     | 最高价格；对应 Ozon `maxPrice`                                                                                                              |
| `sort`            | 否  | `price` / `price_desc` / `relevance` / `newest` | 空     | Ozon 排序方式                                                                                                                            |
| `with_categories` | 否  | boolean                                         | true  | 是否在响应中返回该关键词命中的 Ozon 一级类目列表                                                                                                          |
| `deep_categories` | 否  | boolean                                         | false | 是否在开启 `with_categories` 的前提下，再去请求每个一级类目页，把子类目（来自 `horizontalCategoryMenu`）一并填入 `subcategories` 字段。**开启后接口耗时 ≈ 一级类目数 × 1 次额外请求**，按需启用 |

### 响应

```json
{
  "count": 1,
  "results": [
    {
      "keyword": "dress",
      "requested_pages": 3,
      "pages": 3,
      "unique": 92,
      "returned": 92,
      "items": [
        {
          "id": "...",
          "title": "...",
          "price": "...",
          "original_price": "...",
          "discount": "...",
          "rating": "...",
          "reviews": "...",
          "stock": "...",
          "link": "...",
          "main_image": "..."
        }
      ],
      "categories": [
        {
          "id": "7500",
          "name": "Одежда",
          "level": 0,
          "url": "/category/odezhda-obuv-i-aksessuary-7500/",
          "subcategories": [
            { "id": "7501", "name": "Женская одежда", "level": 1, "url": "...", "parent_id": "7500" }
          ]
        }
      ]
    }
  ]
}
```

`categories` 元素结构：

| 字段              | 说明                                                                              |
| --------------- | ------------------------------------------------------------------------------- |
| `id`            | Ozon 类目数字 ID（字符串）                                                               |
| `name`          | Ozon 俄语/俄哈语原名                                                                   |
| `level`         | 层级：`0`=一级，`1`=二级                                                                |
| `url`           | Ozon 类目页 URL（可拼接 `https://www.ozon.kz` 直接打开）                                    |
| `subcategories` | 子类目列表；仅当 `deep_categories=true` 时填充，且仅包含能被 Ozon 暴露 `horizontalCategoryMenu` 的类目 |

> Ozon 默认一级类目只返回前 3 个；如需让 Dify 在一次调用内掌握"搜索页左侧"全部可见类目（含子类目），请在请求中把 `deep_categories` 设为 `true`。

## 五、错误码

| 状态码    | 含义                         | 处理建议                                      |
| ------ | -------------------------- | ----------------------------------------- |
| 401    | Bearer 缺失、格式错误或与服务端环境变量不一致 | 在 Dify 工具鉴权处重新粘贴密钥                        |
| 409    | 后端未注入 Ozon Cookie          | 打开 `picks.html` → 粘贴 Cookie Header → 重新调用 |
| 422    | 参数越界（如 `pages` 超过 20）      | 按错误体修正参数                                  |
| 400    | Ozon 接口执行失败（如被风控）          | 降低 `pages` 与 `target`，稍后重试                |
| 502/超时 | 映射后端不可达                    | 检查 `9001` 监听状态，必要时重启 `tusou-start.ps1`    |

## 六、智能体系统提示词模板

```text
你是一个 Ozon 选品助手，可以调用工具 ozon_product_search 检索 Ozon 商品。

使用时机：用户希望"搜索 Ozon 上某品类商品"、"分析某关键词的 Ozon 竞争商品"、"查看某类目销量较好的商品"。

参数：
  - keywords：必填数组。中文关键词逐词拆分；一次最多 10 个。
  - pages：默认 3，需要更全面用 5-10。
  - target / preview：默认 120。
  - category：可选。已知 Ozon 类目数字 ID 时直接传，避免无关结果。
  - price_min / price_max：可选。区间筛选，单位 ₽。
  - sort：可选。price / price_desc / relevance / newest。
  - with_categories：默认 true；如不需要类目列表可关闭。
  - deep_categories：默认 false。如需使用 "先看一级类目 → 让智能体挑选 → 再调用锁定类目" 的二级流程，请在首次探查类目时打开它。

推荐两步流程：
  1) 第一次调用：仅 1 个关键词、pages=1、target=5、preview=5、with_categories=true、deep_categories=true → 拿到完整类目树。
  2) 比对返回的 categories[].name 与 categories[].subcategories[].name，挑出用户想要的那一项的 id，作为第二次调用的 category 参数，重新搜索商品。

结果展示：results[].items 包含 id / title / price / rating / reviews / link / main_image；按相关性展示前若干项。

错误处理：
  - 401：让用户重新配置 Dify 鉴权。
  - 409：提醒用户在网页端先导入 Ozon Cookie 后再试。
  - 422/400：修正参数或等待后重试。
```

## 七、自检命令

```powershell
# 本机健康检查
(Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9001/api/health').Content

# 验证 Bearer 与 Cookie 链路（含 deep_categories）
$h = @{ Authorization = 'Bearer TtKQ-HRk0-P-7_owAa9u9IKxp6cKfyLkwPj_tfjclpU' }
$body = '{"keywords":["dress"],"pages":1,"target":3,"preview":3,"deep_categories":true}'
(Invoke-WebRequest -UseBasicParsing -Method Post -Uri 'http://127.0.0.1:9001/api/dify/search' -Headers $h -ContentType 'application/json' -Body $body).Content

# 验证 OpenAPI Schema 可拉取
(Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9001/openapi/dify.json' -Headers $h).Content
```

## 八、安全与维护

- 密钥通过环境变量读取，仓库与前端代码均不含明文。

- 一键启动脚本注入密钥；如需轮换，修改 `tusou-start.ps1` 中默认值后重启服务。

- Cookie 失效时回到 `picks.html` 重新粘贴即可，无需重启服务。

- 当前仅暴露 `/api/dify/search`，未对外暴露 Cookie 管理、任务管理、浏览器代理等接口。

- 若需让 Dify 也具备 Cookie 注入能力，可另外评估是否新增 `POST /api/dify/cookies` 入口。

## 九、后续可选扩展

| 能力              | 是否已支持 | 备注                                              |
| --------------- | ----- | ----------------------------------------------- |
| 多关键词串行搜索        | 是     | 单次最多 10 个                                       |
| 中文→俄语关键词扩展      | 是     | 自动合并去重                                          |
| Ozon 分页续采       | 是     | 含 `nextPage` 与 `page=N` 兜底                      |
| 结果乱码修复          | 是     | UTF-8 + Latin-1 + 多次 mojibake 修复                |
| 类目、价格、排序筛选      | 是     | `category` / `price_min` / `price_max` / `sort` |
| 返回命中类目 ID 与 URL | 是     | `with_categories=true` 时附带一级类目                  |
| 拉取一级类目下的子类目     | 是     | `deep_categories=true` 时附带 `subcategories`      |
| 销量 / 销售额字段      | 否     | 需云启插件或卖家 API                                    |
| 商品上架时间          | 部分    | 仅能通过评论时间戳近似反推                                   |
| 单类目超过 1000 条    | 否     | 服务端硬限 1000，需按类目 × 指标切分                          |

