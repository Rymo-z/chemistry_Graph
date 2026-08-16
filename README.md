# 化工安全生产合规智能体

面向化工企业一线工人的 **7×24 安全生产辅助系统**，数据不出厂、可离线部署。
法规问答 · 拍照识隐患 · 作业票审核 三大能力，知识图谱(Neo4j) 主查 + 向量检索(FAISS) 兜底。

![CI](https://img.shields.io/github/actions/workflow/status/<your-org>/chemistry_Graph/ci.yml?branch=main&label=CI)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ 核心功能

| 功能 | 说明 | 技术路径 |
|------|------|----------|
| 💬 法规制度问答 | 自然语言提问（如“登高作业需要办什么手续？”）秒级返回依据 | 知识图谱(Neo4j) 主查 + 向量检索(FAISS) 兜底 |
| 📷 拍照识隐患 | 上传现场照片，CV 识别隐患、定级、生成整改方案 | YOLOv8 + LLM 定级 + 方案生成 |
| 📋 作业票智能审核 | 自动校验内容缺项、资质合规性 | 规则校验 + LLM 综合分析 |

## 🏗️ 架构总览

```
用户 ──► Streamlit 前端(_006) ──► FastAPI API(_005) ──► LangGraph 状态图(_004)
                                                                │
                          ┌─────────────────────────────────────┼──────────────────────┐
                          ▼                                     ▼                      ▼
                    意图识别                                   实体抽取               YOLO 识别
                          │                                     │                      │
              ┌───────────┼───────────┐              ┌──────────▼─────────┐            │
              ▼           ▼           ▼              │ 生成 Cypher        │            ▼
           QA 路径     HAZARD 路径  PERMIT 路径       │  → 自省校验        │        隐患定级
              │           │           │              │  → 执行(Neo4j)     │            │
              │           │           │              └──────┬─────────────┘        方案生成
              │           │           ▼                     │空结果/失败↓              │
              │           │        票证审核                 ▼  FAISS 向量兜底           │
              │           │           │                     │                        │
              └───────────┴───────────┴─────────────────────┴────────────────────────┘
                                                ▼
                                        统一输出 Markdown
```

数据链路：`采集 → 抽取 → 建图 → 导出元数据 → FAISS 索引`（见下方「完整数据链路」）。

## 🗂️ 模块说明

| 目录 | 职责 |
|------|------|
| `common/` | 公共单例：配置、LLM 客户端、Neo4j 驱动、Embedding+FAISS、日志、路径工具 |
| `_001_clawler/` | 数据采集层（法规/事故爬虫 + 危化品目录解析） |
| `_002_extract_information/` | 知识抽取层：LLM 从文本抽取实体/关系 → JSON |
| `_003_create_neo4j_database/` | 知识存储层：JSON 导入 Neo4j、导出元数据、构建 FAISS 索引 |
| `_004_langgraph_more_nodes/` | ⭐ 核心推理引擎：LangGraph 状态图（12 节点 + Fallback 路由） |
| `_005_fastapi/` | API 服务层：`/chat`、`/detect_hazard`、`/check_permit` |
| `_006_streamlit/` | 前端演示层：侧边栏导航 + 3 个功能页 |
| `_007_fine_tune/` | 模型微调预留：抽取结果 → QA 训练对 |
| `scripts/` | 工程脚本：模型下载 / 示例数据生成 / 数据链路一键重建 |
| `sample_data/` | 示例数据集（20 化学品 + 10 法规 + 8 作业票 + FAISS 种子，开箱 demo） |
| `tests/` | 单元测试（91 passed + 2 skipped） |

## 🚀 快速开始

### 方式 A：一键体验（示例数据，无需爬取数据）

仓库内已附示例数据集（`sample_data/`），新用户 clone 后无需完整爬取数据即可体验 RAG demo。

```bash
# 1. 安装依赖（建议 conda / venv，Python 3.10+）
pip install -r requirements.txt

# 2. 生成配置并填入密钥
cp .env.example .env        # 编辑 LLM_API_KEY（必填）、NEO4J_PASSWORD 等

# 3. 下载模型到 models/（bge-large-zh-v1.5 ~1.3GB + yolov8n.pt；本机已有 bge 可用 --from-local 复制）
python scripts/download_models.py

# 4. 开启示例数据模式
#    .env 中设 USE_SAMPLE_DATA=true

# 5. 一键启动（后端 8000 + 前端 8501）
#    Windows: 双击 start.bat ；Linux/macOS/Git-Bash: ./start.sh
```

浏览器打开 http://127.0.0.1:8501，即可体验问答 / 拍照识隐患 / 作业票审核。

> 示例模式问答走 FAISS 向量检索（无需 Neo4j）；Neo4j 图谱功能需完整数据模式。

### 方式 B：完整数据链路（全量法规/事故/危化品目录）

```bash
# 1. 采集数据（法规 / 事故 / 危化品目录）
python -m _001_clawler.run_crawler regulation --limit 50
python -m _001_clawler.run_crawler gov
python -m _001_clawler.run_crawler accident --limit 20
python -m _001_clawler.organize_data

# 2. 一键重建数据链路（组织 → 抽取 → 建图 → 导出 → FAISS 索引）
#    前置：Neo4j 已启动、embedding 模型就绪
python scripts/rebuild_pipeline.py

# 3. .env 设 USE_SAMPLE_DATA=false，然后按方式 A 第 5 步启动
```

### 可选：Docker 一键编排

```bash
docker compose up -d --build
# 前端 http://127.0.0.1:8501   后端文档 http://127.0.0.1:8000/docs
# 默认示例数据模式；导入数据（示例或全量）：
docker compose run --rm api python -m _003_create_neo4j_database.graph_importer
```

详见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 📡 API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/chat` | 对话问答，`{"question": "登高作业需要办理什么手续？"}` |
| `POST` | `/detect_hazard` | 图片识别隐患（multipart：`file` + 可选 `question` 表单字段） |
| `POST` | `/check_permit` | 作业票审核，`{"permit_data": {...}}` |
| `GET` | `/health` | 健康检查（含 Neo4j 连通状态） |

## ⚙️ 关键设计

- **图查询自省**：`check_cypher_node` 对 LLM 生成的 Cypher 做写操作拦截 + 括号配平 + `EXPLAIN` 双重校验，不合格自动走 FAISS 向量兜底，保证查询零写入风险。
- **级联 Fallback**：图查询无结果/异常 → FAISS 语义检索 → 仍未命中则友好提示，系统不因单点失败而中断。
- **单例封装**：LLM / Neo4j / Embedding 均为懒加载单例，线程安全，适配高并发。
- **可离线**：全部配置走 `.env`，本地 vLLM + 本地 embedding + YOLO 权重 + Neo4j/FAISS 即构成完全离线闭环。
- **示例模式**：`USE_SAMPLE_DATA=true` 时数据/索引目录指向 `sample_data/`，无完整数据也能跑通 RAG。

## 📊 依赖版本

- Python 3.10+（全程 Type Hints）
- LangGraph 状态图（禁用旧版 LangChain Chain）
- Neo4j 4.4（实体关系图）+ FAISS（法规语义索引）
- FastAPI（异步 REST）+ Streamlit（演示前端）
- YOLOv8 / PPED 微调（隐患识别，mAP50 0.620）

## 🔒 安全说明

- `.env` 已 gitignore，密钥不入库；**发布前请轮换 `.env` 中的 LLM API Key 与 Neo4j 密码**。
- Cypher 生成层拦截所有写操作，仅允许只读查询。
- 所有内部数据不出厂，满足化工企业数据安全要求。

## 🤝 贡献

欢迎提交 Issue / PR。请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；本地改动请确保 `python -m pytest -q` 全绿。

## 📄 数据来源与版权

- **法规/事故文本**：应急管理部、中国政府网等公开来源，版权归发布机关所有。仓库内仅随附少量示例（`sample_data/`，法规仅标题+摘要，不含全文）。
- **《危险化学品目录（2015版）》**：应急管理部公告附件，2828 种，本仓库仅随附 20 种示例；完整目录请运行 `_001_clawler/chemical_parser.py`（源 doc 需自行按官方公告获取）。
- **GB 30871-2022 八大特殊作业**：依据标准文本整理的结构化数据，`sample_data/work_permits.json` 为完整副本。
- **模型权重**：bge-large-zh-v1.5（HuggingFace）、YOLOv8（Ultralytics，AGPL-3.0），版权归各自作者。

## ⚠️ 免责声明

本项目仅供**学习/研究**用途，不构成任何安全生产监管、法律或工程判断的依据。
系统输出可能存在偏差，实际生产环境请以权威法规、标准原文与专业审核为准。使用本项目产生的任何后果由使用者自行承担。
