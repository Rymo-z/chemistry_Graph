"""依赖注入：全局共享的 LangGraph app 实例。

模块级构建一次，所有路由通过 `Depends(get_graph_app)` 复用同一实例，
避免每次请求重新编译状态图的开销。
"""
from __future__ import annotations

from typing import Any

from _004_langgraph_more_nodes.graph_builder import get_app

_graph_app: Any = None


def get_graph_app() -> Any:
    """返回全局 LangGraph 应用（懒加载单例）。"""
    global _graph_app
    if _graph_app is None:
        _graph_app = get_app()
    return _graph_app
