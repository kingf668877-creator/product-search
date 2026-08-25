# Ozon Data Terminal

本项目是一个本地运行的 Ozon 选品与商品采集工具，包含：

- **FastAPI 后端**：从 Chrome 导入会话 Cookie 后，按 `nextPage` 顺序翻页调用 Ozon 搜索接口，解析商品标题、价格、评分、评价、库存、主图等字段。
- **Typer 命令行**：支持本地启动服务、导入 Cookie、查看任务、导出 CSV/JSON。
- **本地网页**：分两屏展示
  - `index.html` — 数据终端：导入 Cookie、提交搜索请求、查看/导出任务
  - `picks.html` — 选品库浏览：类目、关键词、排序、筛选、分页，类目化展示搜索结果

## 快速开始

```bash
# 安装依赖
python -m pip install -e ".[test]"

# 启动本地服务（默认监听 0.0.0.0:9001）
python -m ozon_terminal serve --host 0.0.0.0 --port 9001

# 本机浏览器访问
# 1) 数据终端 http://127.0.0.1:9001/
# 2) 选品库   http://127.0.0.1:9001/picks.html

# 如已配置反向代理，也可访问映射域名
# 1) 数据终端 https://yidong.dianleida.net:21997/
# 2) 选品库   https://yidong.dianleida.net:21997/picks.html
```

## 字段说明

搜索响应中可稳定获取的字段：

| 字段       | 来源                                      |
| ---------- | ----------------------------------------- |
| 商品 ID    | `tileGridDesktop.widgetStates.items[].id` |
| 标题       | `textDS.id == "name"`                    |
| 现价 / 原价 / 折扣 | `priceV2`                       |
| 评分值     | `labelListV2`                            |
| 评分数     | `labelListV2`                            |
| 库存提示   | `textDS`（如 `620 шт осталось`）         |
| 商品链接   | `action.link`                            |
| 主图       | `tileImage.items[0].image.link`          |

店铺名称 / 真实销量 Ozon 搜索接口不公开，需要二次抓详情或第三方监控数据。

## 安全说明

- 默认端口 9001，默认监听 `0.0.0.0`，方便被内网或反向代理访问
- Cookie 会上传到内存中，且在收到 `POST /api/cookies/header` 或 `POST /api/cookies/import` 时自动写入本地 SQLite，方便服务重启后自动恢复
- 不会随 CSV/JSON 导出；服务退出或调用 `DELETE /api/cookies` 时会同时清除内存与数据库
- Ozon 的会话 token 有 TTL，过期后需重新粘贴 Cookie Header

## 仓库地址

- 默认远端：`<your-account>/product-search`
