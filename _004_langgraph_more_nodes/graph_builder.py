"""构建 LangGraph 状态图：编排节点、定义路由（并行混合检索）。

链路总览：
  START → intent
    ├─ QA     → entity
    │            ├→ rag（向量检索 + 1 跳图扩展，恒跑，并行）
    │            └→ generate_cypher → check_cypher ─(无效)→ output
    │                                         └─(有效)→ run_cypher → output
    ├─ HAZARD → image → judge → solution → output
    └─ PERMIT → permit → output
  output → END

QA 采用「向量 + 图谱并行混合」：向量检索与图查询同时进行，证据在 output 合并。
任一分支失败只影响该分支，回答仍可基于另一分支证据生成。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from _004_langgraph_more_nodes.agent_state import AgentState
from _004_langgraph_more_nodes.nodes import (
    check_cypher_node,
    entity_node,
    generate_cypher_node,
    hazard_judge_node,
    image_recognition_node,
    intent_node,
    output_node,
    permit_check_node,
    rag_retrieval_node,
    run_cypher_node,
    solution_generate_node,
)
from common.logger import get_logger

logger = get_logger(__name__)


def _route_by_intent(state: AgentState) -> str:
    """根据意图路由到三条子链路。"""
    return (state.get("intent") or "qa").lower()


def _validate(state: AgentState) -> AgentState:
    """入口校验：空/纯空白问题直接短路，避免空查询触发 match-all 图查询。"""
    if not (state.get("question") or "").strip():
        return {
            "output": "请描述您想咨询的化工安全生产问题，例如：\n"
            "- 「登高作业需要办理什么手续？」\n"
            "- 「储罐区闻到异味怎么办？」\n"
            "- 「帮我检查这张动火作业票缺什么」",
            "sources": [],
            "metadata": {"intent": "qa", "graph_hits": 0, "vector_hits": 0},
        }
    return {}


def _route_after_validate(state: AgentState) -> str:
    """问题为空 → 直接结束；否则进入意图识别。"""
    return "__end__" if not (state.get("question") or "").strip() else "intent"


def _route_after_cypher_check(state: AgentState) -> str:
    """Cypher 校验通过 → 执行；不通过 → 直接输出（向量分支已并行完成）。"""
    return "run_cypher" if state.get("cypher_valid") else "output"


def build_graph() -> Any:
    """构建并编译状态图。"""
    graph = StateGraph(AgentState)

    # ---- 注册节点 ----
    graph.add_node("validate", _validate)
    graph.add_node("intent", intent_node)
    graph.add_node("entity", entity_node)
    graph.add_node("generate_cypher", generate_cypher_node)
    graph.add_node("check_cypher", check_cypher_node)
    graph.add_node("run_cypher", run_cypher_node)
    graph.add_node("rag", rag_retrieval_node)
    graph.add_node("image", image_recognition_node)
    graph.add_node("judge", hazard_judge_node)
    graph.add_node("solution", solution_generate_node)
    graph.add_node("permit", permit_check_node)
    graph.add_node("output", output_node)

    # ---- 入口校验 + QA 主链路（向量 + 图谱并行混合） ----
    graph.add_edge(START, "validate")
    graph.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"__end__": END, "intent": "intent"},
    )
    graph.add_conditional_edges(
        "intent",
        _route_by_intent,
        {"qa": "entity", "hazard": "image", "permit": "permit"},
    )
    # entity 同时触发两条并行分支：向量检索恒跑；图谱查询走 Cypher 校验
    graph.add_edge("entity", "rag")
    graph.add_edge("entity", "generate_cypher")
    graph.add_edge("generate_cypher", "check_cypher")
    graph.add_conditional_edges(
        "check_cypher",
        _route_after_cypher_check,
        {"run_cypher": "run_cypher", "output": "output"},
    )
    graph.add_edge("run_cypher", "output")
    graph.add_edge("rag", "output")

    # ---- HAZARD / PERMIT 链路 ----
    graph.add_edge("image", "judge")
    graph.add_edge("judge", "solution")
    graph.add_edge("solution", "output")
    graph.add_edge("permit", "output")

    graph.add_edge("output", END)
    return graph.compile()


def get_app() -> Any:
    """获取编译后的 LangGraph 应用（供 FastAPI 依赖注入与脚本复用）。"""
    return build_graph()


# 模块级单例：服务启动时构建一次，供 API/前端共用
app = get_app()


def run_chat(question: str, **extra: Any) -> dict[str, Any]:
    """便捷入口：注入一个问题并返回完整状态结果。"""
    state: dict[str, Any] = {"question": question}
    state.update(extra)
    result = app.invoke(state)
    return dict(result)
