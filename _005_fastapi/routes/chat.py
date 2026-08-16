"""POST /chat（阻塞）与 POST /chat/stream（SSE 流式）对话接口：法规制度问答。"""
from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from _005_fastapi.dependencies import get_graph_app
from _005_fastapi.models.request_response import ChatRequest, ChatResponse
from common.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["chat"])

# 节点名 -> 进度提示（SSE progress 事件）
_PROGRESS_MSGS: dict[str, str] = {
    "validate": "正在校验问题…",
    "intent": "正在识别问题意图…",
    "entity": "正在提取关键实体…",
    "generate_cypher": "正在生成图查询…",
    "check_cypher": "正在校验查询…",
    "run_cypher": "正在检索知识图谱…",
    "rag": "正在向量检索…",
    "image": "正在分析图像…",
    "judge": "正在评估隐患等级…",
    "solution": "正在生成整改方案…",
    "permit": "正在审核作业票…",
}


def _sse(event: dict[str, Any]) -> str:
    """SSE 事件行：`data: {json}\n\n`。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat", response_model=ChatResponse, summary="法规制度问答")
def chat(req: ChatRequest, app=Depends(get_graph_app)) -> ChatResponse:
    """调用 LangGraph 状态图，返回 Markdown 回答与来源。"""
    logger.info("收到 /chat 请求：%s", req.question[:80])
    try:
        result = app.invoke({"question": req.question})
        return ChatResponse(
            answer=result.get("output") or "抱歉，暂时无法生成回答。",
            intent=result.get("intent"),
            sources=result.get("sources") or [],
            metadata=result.get("metadata") or {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("/chat 处理异常")
        raise HTTPException(status_code=500, detail=f"处理失败: {exc}") from exc


@router.post("/chat/stream", summary="法规制度问答（SSE 流式）")
def chat_stream(req: ChatRequest, app=Depends(get_graph_app)) -> StreamingResponse:
    """SSE 流式对话：检索进度（progress）+ 答案增量（token）+ 收尾（done/error）。

    依赖 LangGraph `stream_mode=["updates","custom"]`：
    - updates 事件 → 节点完成的 progress 提示；
    - custom 事件 → output_node 内 writer 写入的 token 增量。
    """

    def gen() -> Iterator[str]:
        state: dict[str, Any] = {"question": req.question, "stream": True}
        final_output: str = ""
        sources: list[str] = []
        metadata: dict[str, Any] = {}
        try:
            for mode, payload in app.stream(state, stream_mode=["updates", "custom"]):
                if mode == "updates":
                    for node, val in (payload or {}).items():
                        if node == "output":
                            final_output = (val or {}).get("output") or ""
                            sources = (val or {}).get("sources") or []
                            metadata = (val or {}).get("metadata") or {}
                        elif node in _PROGRESS_MSGS:
                            yield _sse({
                                "type": "progress",
                                "node": node,
                                "message": _PROGRESS_MSGS[node],
                            })
                elif mode == "custom":
                    # output_node 写入的 {"type":"token","content":...}
                    yield _sse(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("/chat/stream 处理异常")
            yield _sse({"type": "error", "message": f"处理失败: {exc}"})
            return
        yield _sse({
            "type": "done",
            "output": final_output,
            "sources": sources,
            "metadata": metadata,
        })

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
