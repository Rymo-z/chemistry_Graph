# 化工安全生产合规智能体

面向化工企业（如河北鑫海化工等）一线工人的 **7×24 安全生产辅助系统**，数据不出厂、可离线部署。

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

## 🗂️ 模块说明

| 目录 | 职责 |
|------|------|
| `common/` | 公共单例：配置、LLM 客户端、Neo4j 驱动、Embedding+FAISS、日志、路径工具 |
| `_001_clawler/` | 数据采集层（法规/事故爬虫基类 + 占位实现） |
| `_002_extract_information/` | 知识抽取层：LLM 从文本抽取实体/关系 → JSON |
| `_003_create_neo4j_database/` | 知识存储层：JSON 导入 Neo4j、导出元数据、构建 FAISS 索引 |
| `_004_langgraph_more_nodes/` | ⭐ 核心推理引擎：LangGraph 状态图（12 节点 + Fallback 路由） |
| `_005_fastapi/` | API 服务层：`/chat`、`/detect_hazard`、`/check_permit` |
| `_006_streamlit/` | 前端演示层：侧边栏导航 + 3 个功能页 |
| `_007_fine_tune/` | 模型微调预留：抽取结果 → QA 训练对 |
| `tests/` | 单元测试（Neo4j 连通性、Cypher 校验器） |

## 🚀 快速开始

```bash
# 1. 安装依赖（建议虚拟环境）
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 配置环境变量（LLM / Neo4j / 向量模型）
cp .env .env   # 编辑 .env 填入真实密钥

# 3. 数据链路（可选，已有数据/索引可跳过）
#    采集 → 抽取 → 入图 + 建索引
python -m _003_create_neo4j_database.graph_importer     # 清库 + 导入 _002/output/*.json
python -m _003_create_neo4j_database.metadata_export    # 导出节点文本与元数据
python -m _003_create_neo4j_database.faiss_indexer      # 构建 FAISS 向量索引

# 4. 启动后端 API
uvicorn _005_fastapi.main:app --host 0.0.0.0 --port 8000

# 5. 启动前端
streamlit run _006_streamlit/app.py
```

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
- **反馈闭环**：抽取结果即微调数据源（`_007_fine_tune/prepare_data.py`），持续优化小模型。

## 📊 依赖版本

- Python 3.10+（全程 Type Hints）
- LangGraph 状态图（禁用旧版 LangChain Chain）
- Neo4j（实体关系图）+ FAISS（法规语义索引）+ JSON（元数据缓存）
- FastAPI（异步 REST）+ Streamlit（演示前端）

## 🔒 安全说明

- `.env` 已 gitignore，密钥不入库。
- Cypher 生成层拦截所有写操作，仅允许只读查询。
- 所有内部数据不出厂，满足化工企业数据安全要求。
