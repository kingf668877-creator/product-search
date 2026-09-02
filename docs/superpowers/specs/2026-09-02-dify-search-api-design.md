# Dify Ozon 搜索接口设计

## 目标

将现有 Ozon 关键词搜索能力封装为可由 Dify 智能体安全调用的 HTTP 工具，同时保持现有网页搜索和 Cookie 管理流程不变。

## 访问边界

新增专用入口 `POST /api/dify/search`。该入口仅提供商品搜索，不公开 Cookie 上传、Cookie 清理、浏览器代理、通用任务和导出管理能力。

调用方必须在请求头提供：

```text
Authorization: Bearer <DIFY_API_KEY>
```

服务从 `OZON_DIFY_API_KEY` 环境变量读取密钥。未配置该变量时，Dify 入口默认拒绝调用，避免意外暴露搜索能力。密钥不得写入前端、仓库、OpenAPI 文件或日志。

## 请求合约

```json
{
  "keywords": ["外套", "男士"],
  "pages": 3,
  "target": 120,
  "preview": 120
}
```

- `keywords`：必填，去空格并去重后为 1 到 10 个关键词；每项长度不超过 120。
- `pages`：每个关键词最多采集页数，默认 3，范围 1 到 20。
- `target`：每个关键词最大返回商品数，默认 120，范围 1 到 500。
- `preview`：每个关键词响应中保留的商品数，默认 120，范围 1 到 500，且不超过 `target`。

关键词按顺序串行执行，沿用现有 Ozon Cookie、关键词扩展、相关性排序、分页和乱码修复逻辑，避免并发放大 Ozon 风控风险。

## 响应合约

成功时返回批次摘要和每个关键词的独立结果：

```json
{
  "count": 2,
  "results": [
    {
      "keyword": "外套",
      "requested_pages": 3,
      "pages": 3,
      "unique": 92,
      "items": []
    }
  ]
}
```

`items` 沿用现有搜索字段：`id`、`title`、`price`、`original_price`、`discount`、`rating`、`reviews`、`stock`、`link`、`main_image` 和 `images`。

错误规范：

- `401`：缺少、格式错误或无效的 Bearer 密钥。
- `409`：后端未加载 Ozon Cookie。
- `422`：请求参数超出约束。
- `400`：Ozon 搜索执行失败。

## OpenAPI 导入

新增 `GET /openapi/dify.json`，返回一个独立、精简的 OpenAPI 3.0 文档，仅包含 `searchOzonProducts` 操作和 Bearer 鉴权定义。Dify 通过该地址导入工具；随后在 Dify 工具鉴权处填写与服务环境变量一致的密钥。

现有 FastAPI `/openapi.json` 保持原样，避免把管理接口误导入 Dify。

## 配置与发布

运行服务的启动环境新增：

```text
OZON_DIFY_API_KEY=<高随机性密钥>
```

先在本地以临时测试密钥验证。部署时将同一环境变量写入实际启动脚本或服务配置后重启 `9001` 服务。GitHub Pages 不持有该密钥，也不调用 Dify 专用入口。

## 验证

新增自动化测试覆盖：

1. 未携带密钥和错误密钥均返回 401。
2. 正确密钥可对单个和多个关键词调用。
3. 多关键词按请求顺序串行处理。
4. 关键词、页数、目标数量和预览数量的上下界校验。
5. OpenAPI 文档只包含 Dify 搜索路径与 Bearer 鉴权。
6. 现有网页搜索测试继续通过。
