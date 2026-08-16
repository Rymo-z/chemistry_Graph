"""Streamlit 前端与后端 FastAPI 的通信客户端。

注：本文件为目录树之外新增的轻量辅助模块（避免 app.py 与 pages 相互导入造成
循环依赖），仅承载 API_BASE 配置与统一请求封装。
"""
from __future__ import annotations

import json
import os
from typing import Any, Iterator, Optional

import requests
import streamlit as st

API_BASE: str = os.getenv("API_BASE", "http://127.0.0.1:8000")


def call_api(
    method: str,
    path: str,
    *,
    files: Optional[dict[str, Any]] = None,
    data: Optional[dict[str, Any]] = None,
    json: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """调用后端接口，异常统一在页面提示。

    Args:
        method: GET/POST/PUT/DELETE。
        path: 接口路径，如 /chat。
        files: 上传文件字典 {字段名: (文件名, bytes, content_type)}。
        data: multipart 表单字段。
        json: JSON 请求体。
        params: URL 查询参数。

    Returns:
        后端返回的 dict；失败时返回 {} 并在页面显示错误。
    """
    try:
        response = requests.request(
            method,
            f"{API_BASE}{path}",
            files=files,
            data=data,
            json=json,
            params=params,
            timeout=180,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"后端调用失败（{API_BASE}{path}）：{exc}")
        return {}


def stream_chat(question: str) -> Iterator[dict[str, Any]]:
    """流式调用 /chat/stream（SSE），逐个 yield 解析后的事件字典。

    事件类型：progress（检索进度）/ token（答案增量）/ done（收尾）/ error。
    """
    try:
        with requests.post(
            f"{API_BASE}/chat/stream",
            json={"question": question},
            stream=True,
            timeout=180,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                try:
                    yield json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
    except Exception as exc:  # noqa: BLE001
        st.error(f"流式调用失败（{API_BASE}/chat/stream）：{exc}")
        yield {"type": "error", "message": str(exc)}
