# 数据目录说明（`_001_clawler/data`）

本目录存放化工安全生产合规智能体的原始采集数据与整合产物。
数据仅供个人学习/研究使用，原始页面文本版权归发布机关。

> 目录结构已稳定，爬虫/整理脚本按此路径读写；本目录已被 `.gitignore` 忽略，
> 仅目录结构与 `.gitkeep` 占位入库，采集产物不入库。

## 目录布局

| 目录 | 用途 | 当前数据 | 写入方 |
| --- | --- | --- | --- |
| `govlaws/` | 法律与行政法规（白名单：gov.cn + 地方政府门户转载） | 10 部 | `gov_crawler.py` |
| `regulations/` | 规范性文件（应急管理部） | 117 篇 | `regulation_crawler.py` |
| `accidents/` | 特别重大事故调查报告（应急管理部） | 91 份 | `accident_crawler.py` |
| `internal_docs/` | 企业内部制度文档（预留） | 占位（待人工录入） | — |

## 生成物（勿手工编辑，由脚本维护）

| 文件 | 说明 | 重新生成 |
| --- | --- | --- |
| `all_records.jsonl` | 整合各源 `structured.jsonl` 的统一记录（共 218 条） | `python -m _001_clawler.organize_data` |
| `OVERVIEW.md` | 人类可读数据清单 | 同上 |

## 各源子目录结构

每个数据源目录（`govlaws/`、`regulations/`、`accidents/`）约定如下：

- `raw/`（或 `pdfs/`）：原始页面 / 报告附件，保留取证
- `structured.jsonl`：规范化记录（每行一条 JSON，爬虫增量追加）
- `crawl_state.json`：断点续爬状态（`--force` 可重置）
- `.gitkeep`：目录占位（保证空目录入库）

## 数据说明

- **accidents PDF 数量少于详情页数**：当前 91 份详情页、仅 20 份 PDF——
  早年事故页面未附 PDF 附件，属数据现实而非缺失。
