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
   ↓  分页、关键词扩展、类目解析、乱码修复
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

> 密钥目前保存在桌面上的“一键启动图搜.bat → tusou-start.ps1”中，开机自启时会自动注入环境变量。

## 三、Dify 后台接入步骤

### 1. 创建自定义工具

1. 登录 Dify → 进入目标工作区。
2. 顶部菜单 `工具` → `自定义工具`。
3. 点击 `创建自定义工具`，类型选择 `OpenAPI Schema`。

### 2. 填写工具元数据

| 字段   | 值                                        |
| ---- | ---------------------------------------- |
| 工具名称 | `ozon_product_search`                    |
| 工具描述 | 使用登录态 Ozon 账号进行关键词搜索，返回商品、命中类目、价格、评分等字段。 |

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
  "preview": 5,
  "with_categories": true
}
```

期望返回 200，且 `results[0].keyword == "外套"`，`results[0].categories` 包含类目 ID 与名称。

## 四、参数与响应契约

### 请求

```json
{
  "keywords": ["外套", "男士"],
  "pages": 3,
  "target": 120,
  "preview": 120,
  "category": "7500",
  "price_min": 1000,
  "price_max": 3000,
  "sort": "price",
  "with_categories": true
}
```

| 参数                | 必填 | 范围                                              | 默认     | 说明                            |
| ----------------- | -- | ----------------------------------------------- | ------ | ----------------------------- |
| `keywords`        | 是  | 1-10 个，每个长度 ≤120                                | -      | 串行执行，原词 + 中文/俄语扩展词合并去重        |
| `pages`           | 否  | 1-20                                            | 3      | 每个关键词最多采集页数                   |
| `target`          | 否  | 1-500                                           | 120    | 每个关键词最大返回商品数                  |
| `preview`         | 否  | 1-500，不大于 target                                | 120    | 响应中保留的商品数                     |
| `category`        | 否  | Ozon 类目 ID，长度 ≤64                               | -      | Ozon 类目数字 ID（如 7500 表示服装鞋与配饰） |
| `price_min`       | 否  | 0-10,000,000                                    | -      | 最低价格（₽）                       |
| `price_max`       | 否  | 0-10,000,000，不小于 price\_min                     | -      | 最高价格（₽）                       |
| `sort`            | 否  | `price` / `price_desc` / `relevance` / `newest` | -      | Ozon 排序方式                     |
| `with_categories` | 否  | `true` / `false`                                | `true` | 是否在响应中返回命中类目列表                |

### 响应

```json
{
  "count": 2,
  "results": [
    {
      "keyword": "dress",
      "requested_pages": 1,
      "pages": 1,
      "unique": 30,
      "returned": 30,
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
        { "id": "7500", "name": "Одежда", "level": 0, "url": "/category/odezhda-obuv-i-aksessuary-7500/?..." },
        { "id": "30931", "name": "Ароматы для дома", "level": 0, "url": "/category/aromaty-dlya-doma-30931/?..." },
        { "id": "33332", "name": "Туризм, рыбалка, охота", "level": 0, "url": "/category/ohota-rybalka-turizm-33332/?..." }
      ]
    }
  ]
}
```

- `items` 字段沿用之前的商品结构。

- `categories` 字段在以下情况可能为空数组：

  - 显式传了 `category`（表示已锁定类目）

  - 显式传了 `with_categories: false`

  - Ozon 接口没有返回类目树 widget 或解析失败

## 五、典型调用流程

### 1. 仅用关键词搜索

```json
{
  "keywords": ["dress"],
  "pages": 3,
  "target": 120,
  "preview": 120
}
```

适用场景：不知道该关键词在 Ozon 上属于什么类目，希望让 Ozon 自己判断。

### 2. 类目精准筛选（首次 + 二次）

第一次调用不传 `category`，让 Dify 从 `categories` 里挑一个：

```json
{
  "keywords": ["dress"],
  "pages": 1,
  "target": 5,
  "preview": 5,
  "with_categories": true
}
```

返回 `results[0].categories`，每项含 `id`（Ozon 类目 ID）、` ` name`（Ozon 原俄/哈语名）、` `level`、` ` url\`。

第二次调用把选中的 `id` 作为 `category` 参数传入，并关闭类目字段以减小响应体：

```json
{
  "keywords": ["dress"],
  "pages": 3,
  "target": 120,
  "preview": 120,
  "category": "7500",
  "with_categories": false
}
```

### 3. 价格区间筛选

```json
{
  "keywords": ["куртка"],
  "category": "7500",
  "price_min": 1000,
  "price_max": 3000,
  "sort": "price"
}
```

### 4. 排序

```json
{
  "keywords": ["платье"],
  "sort": "newest"
}
```

## 六、错误码

| 状态码    | 含义                                              | 处理建议                                      |
| ------ | ----------------------------------------------- | ----------------------------------------- |
| 401    | Bearer 缺失、格式错误或与服务端环境变量不一致                      | 在 Dify 工具鉴权处重新粘贴密钥                        |
| 409    | 后端未注入 Ozon Cookie                               | 打开 `picks.html` → 粘贴 Cookie Header → 重新调用 |
| 422    | 参数越界（如 `pages` 超过 20 或 `price_max < price_min`） | 按错误体修正参数                                  |
| 400    | Ozon 接口执行失败（如被风控）                               | 降低 `pages` 与 `target`，稍后重试                |
| 502/超时 | 映射后端不可达                                         | 检查 `9001` 监听状态，必要时重启 `tusou-start.ps1`    |

## 七、智能体系统提示词模板

```text
你是一个 Ozon 选品助手，可以调用工具 ozon_product_search 检索 Ozon 商品。

使用时机：用户希望“搜索 Ozon 上某品类商品”、“分析某关键词的 Ozon 竞争商品”、“查看某类目销量较好的商品”。

调用步骤：
  1. 第一次调用不要传 category，传入 keywords 与 with_categories: true。
  2. 响应 results[].categories 含 1-3 个 Ozon 类目（id / name / level / url）。name 是 Ozon 原俄/哈语名。
  3. 把你输入的关键词语义与 categories[].name 做匹配，选择最贴近的一项。
  4. 第二次调用把选中的 id 作为 category 参数传入，并把 with_categories 设为 false，减少响应体积。
  5. 如希望限制价格或排序，使用 price_min / price_max / sort。

结果展示：results[].items 包含 id / title / price / rating / reviews / link / main_image；按相关性展示前若干项。

错误处理：
  - 401：让用户重新配置 Dify 鉴权。
  - 409：提醒用户在网页端先导入 Ozon Cookie 后再试。
  - 422/400：修正参数或等待后重试。
```

## 八、自检命令

```powershell
# 本机健康检查
(Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9001/api/health').Content

# 验证 Bearer 与 Cookie 链路（带类目返回）
$h = @{ Authorization = 'Bearer TtKQ-HRk0-P-7_owAa9u9IKxp6cKfyLkwPj_tfjclpU' }
$body = '{"keywords":["外套"],"pages":1,"target":3,"preview":3,"with_categories":true}'
(Invoke-WebRequest -UseBasicParsing -Method Post -Uri 'http://127.0.0.1:9001/api/dify/search' -Headers $h -ContentType 'application/json' -Body $body).Content

# 验证 OpenAPI Schema 可拉取
(Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9001/openapi/dify.json' -Headers $h).Content
```

## 九、安全与维护

- 密钥通过环境变量读取，仓库与前端代码均不含明文。

- 一键启动脚本注入密钥；如需轮换，修改 `tusou-start.ps1` 中默认值后重启服务。

- Cookie 失效时回到 `picks.html` 重新粘贴即可，无需重启服务。

- 当前仅暴露 `/api/dify/search`，未对外暴露 Cookie 管理、任务管理、浏览器代理等接口。

- 若需让 Dify 也具备 Cookie 注入能力，可另外评估是否新增 `POST /api/dify/cookies` 入口。

## 十、后续可选扩展

| 能力           | 是否已支持 | 备注                                              |
| ------------ | ----- | ----------------------------------------------- |
| 多关键词串行搜索     | 是     | 单次最多 10 个                                       |
| 中文→俄语关键词扩展   | 是     | 自动合并去重                                          |
| Ozon 分页续采    | 是     | 含 `nextPage` 与 `page=N` 兜底                      |
| 结果乱码修复       | 是     | UTF-8 + Latin-1 + 多次 mojibake 修复                |
| 类目筛选         | 是     | `category` 参数透传 Ozon 类目 ID                      |
| 价格区间筛选       | 是     | `price_min` / `price_max`（₽）                    |
| 排序           | 是     | `price` / `price_desc` / `relevance` / `newest` |
| 命中类目返回       | 是     | `categories` 字段（最多 3 个 Ozon 类目）                 |
| 类目+商品数       | 否     | Ozon 左侧筛选面板不返回商品数；可另外触发类目内搜索估算                  |
| 销量 / 销售额字段   | 否     | 需云启插件或卖家 API                                    |
| 商品上架时间       | 部分    | 仅能通过评论时间戳近似反推                                   |
| 单类目超过 1000 条 | 否     | 服务端硬限 1000，需按类目 × 指标切分                          |

