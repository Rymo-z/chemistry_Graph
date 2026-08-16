# 数据采集层设计方案（`_001_clawler`）

> 面向化工安全生产合规智能体的数据需求分析与数据源规划。
> 本文档是 `_001_clawler` 各爬虫实现的开发依据。

- 状态：设计稿 v0.1
- 日期：2026-08-12
- 关联模块：`_001_clawler`（采集）→ `_002_extract_information`（抽取）→ `_003_create_neo4j_database`（入图）

---

## 1. 背景与目标

项目提供三大核心能力，各自依赖不同的数据：

| 功能 | 数据依赖 | 落库方式 |
|------|---------|---------|
| 💬 法规制度问答 | 法规文本、事故案例、危化品数据 | 知识图谱(Neo4j) + FAISS |
| 📷 拍照识隐患 | 隐患图片数据集 | YOLOv8 模型权重 |
| 📋 作业票智能审核 | 八大特殊作业规范、作业票模板 | 规则 + 图谱 |

**本层目标**：以公开、合规的方式采集并落地以上数据，产出结构统一的原始文件，供 `_002` 抽取管线消费。

**数据流约定**：

```
爬虫(crawl) ──► _001_clawler/data/{category}/    原始文本/报告（已 gitignore）
                   │
                   ▼
              清洗/规范化
                   │
                   ▼
              _001_clawler/data/structured/{category}.jsonl   ← _002 抽取层读取
```

> 目录约定与 `.gitignore` 保持一致：`regulations/`、`accidents/`、`internal_docs/`
> 已在忽略规则中预留；新增 `chemicals/`、`standards/` 时同步补充忽略规则。

---

## 2. 数据需求总览

| # | 数据类型 | 服务功能 | 图谱角色 | 优先级 | 获取方式 |
|---|---------|---------|---------|--------|---------|
| 1 | 法规制度（法律/条例/标准/规章） | 法规问答 | 核心节点 | ⭐⭐⭐ | 公开爬取 |
| 2 | 事故案例（调查报告） | 问答、原因分析、警示教育 | 核心节点 | ⭐⭐⭐ | 公开爬取 |
| 3 | 危化品基础数据（名录/MSDS/危险性） | 问答、隐患定级 | 辅助节点 | ⭐⭐ | 公开爬取 |
| 4 | 特殊作业规范（八大作业票） | 作业票审核 | 核心节点+规则 | ⭐⭐⭐ | 公开爬取+整理 |
| 5 | 隐患图片（PPE/明火/泄漏等） | 拍照识隐患 | YOLO 训练数据 | ⭐⭐ | 开源数据集 |
| 6 | 企业规章制度（内部制度/操作规程） | 问答（个性化） | 补充节点 | ⭐ | 人工录入 |

---

## 3. 各类数据明细与来源

### 3.1 法规制度数据

**目标文件清单**（先列这份，覆盖后再扩）：

| 文件 | 文号/标准号 | 说明 |
|------|-----------|------|
| 《安全生产法》 | 主席令 | 上位法 |
| 《危险化学品安全法》 | 2025-12-27 通过 | 最新核心法 |
| 《危险化学品安全管理条例》 | 国务院令 | 危化品全链条管理 |
| 《生产安全事故报告和调查处理条例》 | 国务院令 | 事故分级上报 |
| 《危险化学品企业特殊作业安全规范》 | GB 30871-2022 | 八大作业，作业票核心 |
| 《安全生产事故隐患排查治理暂行规定》等规章 | 应急管理部令 | 按需扩展 |
| 专项标准 | GB / AQ / HG 系列 | 按需扩展 |

**记录结构**（`RegulationCrawler` 输出 schema）：

```python
{
    "title": "法规名称",
    "doc_no": "文号/标准号",
    "category": "法律 | 行政法规 | 部门规章 | 国标 | 行标",
    "publish_date": "YYYY-MM-DD",
    "issuing_org": "发布机关",
    "status": "现行 | 废止 | 修订中",
    "content": "全文文本",
    "url": "来源链接",
    "source_site": "来源站点标识"
}
```

**来源网页**：

| 站点 | URL | 说明 |
|------|-----|------|
| 应急管理部·法律法规标准 | https://www.mem.gov.cn/fw/flfgbz/fg/ | 法律/法规/规章 |
| 应急管理部·规范性文件 | https://www.mem.gov.cn/fw/flfgbz/gfxwj/ | 规范性文件 |
| 应急管理部·公告 | http://www.mem.gov.cn/gk/tzgg/yjbgg/index.shtml | 危化品目录调整等 |
| 国家法律法规数据库 | https://flk.npc.gov.cn | ⚠️ 已弃用（2026-08-13）：WAF 常拒 TLS 指纹、服务端故障无法获取全文，改用 gov 白名单替代 |
| 全国标准信息公共服务平台 | https://std.samr.gov.cn | GB/AQ 标准全文检索 |
| 中国政府网·政策文件库 | https://www.gov.cn/zhengce/ | 国务院文件 |

### 3.2 事故案例数据

**按事故类型归类**：火灾爆炸 / 中毒窒息 / 高处坠落 / 触电 / 机械伤害 / 灼烫 / 泄漏。

**记录结构**（`AccidentCrawler` 输出 schema）：

```python
{
    "title": "事故标题",
    "date": "事发时间 YYYY-MM-DD",
    "location": "事发地点",
    "enterprise": "涉事企业",
    "level": "特别重大 | 重大 | 较大 | 一般",
    "category": "事故类型",
    "summary": "事故经过",
    "cause": "原因分析",
    "responsibility": "责任认定",
    "content": "报告全文",
    "url": "来源链接",
    "source_site": "来源站点标识"
}
```

**来源网页**：

| 站点 | URL | 说明 |
|------|-----|------|
| 应急管理部官网 | https://www.mem.gov.cn | 特别重大事故调查报告全文 |
| 各省应急管理厅 | （按省份逐个对接） | 重大/较大事故调查报告，按调查权限分级发布 |
| 中国化学品安全协会 | https://www.chemicalsafety.org.cn | 事故案例 5500+（部分需会员） |
| 中国安全生产网 | https://www.aqsc.cn | 事故快报/案例 |
| 化工安全教育公共服务平台 | http://ciedu.com.cn | 权威事故解读课程 |

> ⚠️ 事故报告多为 PDF/Word，注意格式解析，见第 5 节。

### 3.3 危化品基础数据

**记录结构**：

```python
{
    "name": "化学品名称",
    "cas_no": "CAS 号",
    "un_number": "UN 编号",
    "hazard_class": "危险分类",
    "hazard_category": "爆炸品 | 易燃 | 有毒 | 腐蚀 ...",
    "msds": "安全技术说明书",
    "flash_point": "闪点",
    "toxicity": "毒性",
    "storage_req": "储存要求",
    "in_catalog": "是否列入《危险化学品目录》"
}
```

**来源网页**：

| 站点 | URL | 说明 |
|------|-----|------|
| 国家危险化学品安全公共服务互联网平台 | https://whpdj.mem.gov.cn/publicInternet/home | 免费查登记信息/SDS/专家解答 |
| 应急管理部·公告栏目 | http://www.mem.gov.cn/gk/tzgg/yjbgg/index.shtml | 《危险化学品目录(2015版)》及调整公告 |

### 3.4 特殊作业 / 作业票数据

**八大特殊作业**：动火 / 受限空间 / 盲板抽堵 / 高处 / 吊装 / 临时用电 / 动土 / 断路。

**记录结构**（每类作业一条）：

```python
{
    "work_type": "动火作业 | 受限空间作业 | ...",
    "definition": "作业定义",
    "grading": "分级标准",
    "permit_fields": "作业票字段清单",
    "approval_flow": "审批权限与流程",
    "safety_measures": "安全措施要求",
    "emergency_req": "应急处置要求",
    "source_std": "依据标准（如 GB 30871-2022）"
}
```

**来源**：

- GB 30871-2022《危险化学品企业特殊作业安全规范》——八大作业的唯一权威依据，全国标准信息公共服务平台可查。
- AQ 3064.2-2025《"工业互联网+危化安全生产"建设规范 第2部分：特殊作业审批与作业过程管理》——作业票线上化/过程管理的行业标准，2026-07-01 实施。

### 3.5 隐患图片数据集（YOLO）

**推荐顺序**（全部兼容 YOLO 格式，可直接训练）：

| 数据集 | 规模/类别 | 特点 | 来源 |
|--------|----------|------|------|
| PPED 化工防护装备数据集 | 3300+ 图 / 6 类 PPE | 基于 GB 39800 国标、化工场景、含 YOLO 标注与基准（YOLOv5 mAP 93.6%） | Zenodo DOI: 10.5281/zenodo.6551758 |
| SH17 制造业安全数据集 | 8099 图 / 75994 实例 / 17 类 | 多源采集、含小目标 | https://github.com/ahmadmughees/sh17dataset |
| PPE_Detection (HuggingFace) | 6 类 / 16014 目标 | Roboflow 标注、含 train/valid 划分 | https://huggingface.co/datasets/51ddhesh/PPE_Detection |
| 工业危害检测（明火/烟雾/泄漏等 5 类） | mAP@0.5 0.697 | 非 PPE 类隐患，最贴合"拍照识隐患" | CSDN 等渠道（注意版权） |

**建议策略**：PPED 打底 + SH17 扩类 + 自有化工现场照片补充，形成 YOLOv8 训练集。

### 3.6 企业规章制度（人工录入）

企业内部制度（如《动火作业管理制度》《承包商安全管理制度》）**无公开来源**，由企业提供或人工整理为结构化 Markdown/JSON 后，直接走 `_002` 抽取管线，不进爬虫层。

---

## 4. 爬虫实现规划

### 4.1 类结构

```
_001_clawler/
├── base_crawler.py        # ✅ 已有：重试/限速/编码探测/保存
├── regulation_crawler.py  # 实现 RegulationCrawler（法规）
├── accident_crawler.py    # 实现 AccidentCrawler（事故）
├── chemical_crawler.py    # 新增：ChemicalCrawler（危化品）
├── standard_crawler.py    # 新增：StandardCrawler（GB/AQ 标准）
└── run_all.py             # 新增：编排入口（可选 / 增量）
```

### 4.2 每类爬虫要点

| 爬虫 | 目标站点 | 关键处理 |
|------|---------|---------|
| RegulationCrawler | mem.gov.cn, gov.cn | 列表页分页 → 详情页正文抽取；正文清洗（去导航/页脚/广告） |
| AccidentCrawler | mem.gov.cn + 省级应急厅 | 附件下载（PDF/Word）→ 文本抽取 |
| ChemicalCrawler | whpdj.mem.gov.cn | JSON API 优先；目录增量同步 |
| StandardCrawler | std.samr.gov.cn | 元数据为主（标准号/名称/状态/实施日期），全文以引用替代 |

### 4.3 通用约定

- **统一输出目录**：`_001_clawler/data/{category}/`（原始文本）+ `_001_clawler/data/structured/`（规范化 JSON）。
- **断点续爬**：已存在且非 `--force` 的原始文件跳过。
- **幂等保存**：`crawl()` 可重复执行不产生重复数据（按 url 去重）。
- **失败不中断**：单条失败记日志并继续，汇总 `crawl()` 返回成功率。

---

## 5. 爬取难点与对策

| 难点 | 对策 |
|------|------|
| 事故报告多为 PDF/Word | 引入 `pdfplumber`/`pypdf`（PDF）、`python-docx`（.docx）解析附件 |
| 不同站点 HTML 结构差异大 | 每站点独立 crawler 子类，解析逻辑互不耦合 |
| 省应急管理厅站点分散 | 先做应急管理部 + 2~3 个重点省份，逐步扩展 |
| 国标平台只给摘要 | 存元数据 + 引用链接，不存付费全文 |
| 站点反爬 | 保持基类限速；必要时加随机 UA 池、Cookie |

---

## 6. 合规与 GitHub 发布规范

1. **尊重 robots.txt 与限速**：基类随机间隔(1~3s) + 指数退避已内置，高频站点调大间隔。
2. **版权边界**：法规/标准文本为公开政务信息可爬；事故报告全文、付费标准只存引用与元数据。
3. **数据不进 Git**：`data/`、`output/` 大文件全部 `.gitignore`，用 `.gitkeep` + `README.md` 说明目录用途。
4. **`.env` 不入库**：确认 `.gitignore` 已含 `.env`（当前已包含）。
5. **来源可溯源**：每条记录保留 `url` 与 `source_site`，既是溯源也是合规声明。
6. **许可证**：README 声明数据来源及各数据集许可证（如 CC-BY-4.0）。
7. **爬取频率约束**：对同一站点设每日抓取上限，防止对政务站点造成压力。

---

## 7. 实施路线

| 阶段 | 内容 | 产出 |
|------|------|------|
| P0 | 实现 RegulationCrawler（法规） | data/structured/regulations.jsonl |
| P1 | 实现 AccidentCrawler（事故） | data/structured/accidents.jsonl |
| P2 | 整理八大作业票模板（GB 30871-2022） | data/structured/work_permits.json |
| P3 | 实现 ChemicalCrawler（危化品） | data/structured/chemicals.jsonl |
| P4 | 下载/整理 YOLO 数据集 | data/yolo/{train,valid,test}/ |
| P5 | 企业制度人工录入模板 | data/structured/company_rules/ |

> 每阶段产出接入 `_002_extract_information` 验证 schema，再进 `_003` 入图。
