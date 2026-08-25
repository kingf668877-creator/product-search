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

# 启动本地服务
python -m ozon_terminal serve --host 127.0.0.1 --port 8000

# 打开浏览器
# 1) 数据终端 http://127.0.0.1:8000/
# 2) 选品库   http://127.0.0.1:8000/picks.html
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

- Cookie 始终只驻留在进程内存中
- 不会写入 SQLite、CSV/JSON 或日志
- 服务退出或调用 `/api/cookies` 时自动清除

## 仓库地址

- 默认远端：`<your-account>/product-search`
