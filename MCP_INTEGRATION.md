# Ozon Data Terminal × Dify MCP 接入指南

## 一、这是什么

`ozon_terminal.mcp_server` 把现有 FastAPI 后端能力拆成 9 个 MCP tool，供给 Dify 1.x 的"MCP 服务器"集成面板使用。LLM 直接看到的是已分解好的 tool 列表（不是单一 endpoint + JSON），可以按 tool name 直接调用。

对比之前的 OpenAPI 自定义工具：MCP 接入更直观，LLM 不必手填整个 JSON body，每个 tool 自带描述和参数 schema。

## 二、运行 MCP server

```powershell
# 安装依赖（一次性）
pip install 'mcp>=1.10,<2.0'

# 启动 MCP server（默认 0.0.0.0:9002，与 FastAPI 后端 9001 共存）
$env:OZON_DIFY_API_KEY = "TtKQ-HRk0-P-7_owAa9u9IKxp6cKfyLkwPj_tfjclpU"  # 可选，目前 MCP server 不强制校验
python -m ozon_terminal.mcp_server --host 0.0.0.0 --port 9002
```

启动后会看到：

```text
INFO:     StreamableHTTP session manager started
INFO:     Uvicorn running on http://0.0.0.0:9002
```

MCP endpoint 路径：`/mcp`（FastMCP 默认 `streamable_http_path = /mcp`）

## 三、Dify 集成面板接入

1. 登录 Dify → 顶部菜单 `工作室` → 选择工作区 → 左侧 `工具` → `MCP`。
2. 点 `安装 MCP`，新增一个 server：

| 字段 | 值 |
| --- | --- |
| Server 名称 | `ozon-terminal` |
| Transport | `streamable_http` |
| URL | `http://127.0.0.1:9002/mcp`（同机）或 `https://<映射域名>:<端口>/mcp`（远程） |
| Headers | `{}`（无需 Bearer） |

3. 保存后 Dify 自动 `initialize` + `tools/list`，右侧会列出 9 个 tool（参考你贴的 MCP 集成截图效果）。

## 四、9 个 MCP Tool 列表

| Tool | 用途 | 关键参数 |
| --- | --- | --- |
| `ozon_search_keyword` | 关键词搜索商品（中文→俄语自动扩展） | `keyword, pages, target, preview, category, price_min, price_max, sort` |
| `ozon_search_category` | 按类目浏览商品 | `category, pages, target, preview, sort` |
| `ozon_get_category_info` | 类目详情 + 子类目 | `category_id, with_subcategories` |
| `ozon_list_categories` | 枚举关键词命中的类目（支持 deep） | `keyword, deep, pages, target, preview` |
| `ozon_product_info` | 单商品详情 | `sku` |
| `ozon_bestsellers` | Ozon 畅销榜（最多 1000 条） | `preset, pages, target, preview` |
| `ozon_search_filtered` | 关键词 + 类目 + 价格 + 排序 | `keyword, category, price_min, price_max, sort, pages, target, preview` |
| `ozon_keyword_tendency` | 趋势估算（基于评论时间戳） | `keyword, pages, target, preview` |
| `ozon_query_list` | 上次查询摘要 | `limit` |

## 五、典型两步流程

```text
1) ozon_list_categories(keyword="dress", deep=true)
   → 返回 [{id:7500, name:"Одежда", subcategories:[...]}]

2) ozon_search_filtered(keyword="dress", category="7501", price_min=1000, price_max=5000)
   → 返回具体商品列表
```

## 六、安全与维护

- MCP server 与 FastAPI 后端**共享同一个 SQLite DB**（`ozon_terminal.db`），Cookie 在两边都能用。
- Cookie 失效时回到 `picks.html` 重新粘贴即可，无需重启 MCP server。
- MCP server 不强制 Bearer 鉴权（适合内网 Dify 与 MCP 同机部署的场景）；如需暴露公网，请在前面套反向代理加鉴权。
- 当前 MCP server 仅暴露 9 个只读 + 搜索类工具，未对外暴露 Cookie 管理、任务管理、浏览器代理等接口。

## 七、自检命令

```powershell
# 1) 启动后探活（POST /mcp 是 streamable_http 入口，HTTP 200 不一定代表协议通，要用 SDK）
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

# 2) 调一次 list_categories 看真实数据
python -c "
import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    async with streamablehttp_client('http://127.0.0.1:9002/mcp') as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool('ozon_list_categories', {'keyword': 'dress', 'deep': True})
            print(res.content[0].text[:300])

asyncio.run(main())
"
```

## 八、与 OpenAPI 自定义工具的关系

| 维度 | OpenAPI 自定义工具（已有） | MCP server（新增） |
| --- | --- | --- |
| 入口 | 单个 `POST /api/dify/search` | 9 个独立 tool |
| LLM 视角 | 看到一个大 JSON body | 看到已分解的 tool 列表 |
| 鉴权 | Bearer（环境变量强制） | 无（内网默认） |
| 协议 | HTTP + OpenAPI 3.0 Schema | MCP streamable_http（JSON-RPC over HTTP） |
| 用途 | 一站式搜索、Dify 工具面板 | 精细化多步流程、Dify 集成面板 |

两者可以并存：FastAPI 后端保留 `/api/dify/search`（OpenAPI 方式），新增 `9002/mcp`（MCP 方式）。