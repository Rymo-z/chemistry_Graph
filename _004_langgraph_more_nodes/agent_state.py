"""定义 AgentState（TypedDict）：贯穿 LangGraph 各节点的共享状态。

所有节点以「返回部分状态字典」的方式更新 state，由 LangGraph 自动合并。
total=False 表示字段均可选，节点按需填充。
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """全图共享状态。"""

    # ---------------- 输入 ----------------
    question: str                              # 用户自然语言问题
    image_path: Optional[str]                  # 上传图片路径
    permit_data: Optional[dict[str, Any]]      # 作业票结构化字段
    stream: Optional[bool]                     # 流式输出开关（/chat/stream 注入）

    # ---------------- 语义解析 ----------------
    intent: Optional[str]                      # QA | HAZARD | PERMIT
    entities: dict[str, list[str]]             # 抽取的实体 {equipment:[], operation:[], ...}

    # ---------------- 图查询链路 ----------------
    cypher_query: Optional[str]                # LLM 生成的 Cypher
    cypher_params: Optional[dict[str, Any]]    # Cypher 参数化查询的参数（$kw/$op/...）
    cypher_valid: bool                         # check_cypher 校验结果
    cypher_error: Optional[str]                # 校验失败原因
    graph_result: list[dict[str, Any]]         # Neo4j 查询结果

    # ---------------- RAG 链路 ----------------
    rag_results: list[dict[str, Any]]          # FAISS 检索结果 [{score, node}]

    # ---------------- 隐患链路 ----------------
    yolo_detections: list[dict[str, Any]]      # CV 检测结果
    hazard_level: Optional[str]                # 隐患等级
    hazard_reason: Optional[str]               # 定级依据
    solution: Optional[str]                    # 整改方案

    # ---------------- 作业票链路 ----------------
    permit_result: Optional[dict[str, Any]]    # 审核结论 {passed, missing_fields, issues, ...}

    # ---------------- 输出 ----------------
    output: Optional[str]                      # 最终 Markdown 回答
    sources: list[str]                         # 引用来源
    metadata: dict[str, Any]                   # 附加元数据（意图/耗时等）
    error: Optional[str]                       # 链路中的非致命错误记录
