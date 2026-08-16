"""Pydantic 请求/响应模型（API 契约）。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------- 请求模型 ----------------
class ChatRequest(BaseModel):
    """法规制度问答请求。"""

    question: str = Field(..., min_length=1, max_length=4000, description="用户自然语言问题")


class DetectHazardRequest(BaseModel):
    """隐患识别请求（图片以 multipart 上传，此模型仅承载可选补充字段）。"""

    question: Optional[str] = Field(default=None, max_length=2000, description="可选的文字补充描述")


class PermitCheckRequest(BaseModel):
    """作业票审核请求。"""

    permit_data: dict[str, Any] = Field(..., description="作业票结构化字段")
    question: Optional[str] = Field(default=None, max_length=2000, description="可选的附加要求")


# ---------------- 响应模型 ----------------
class ChatResponse(BaseModel):
    """对话问答响应。"""

    answer: str = Field(..., description="Markdown 格式回答")
    intent: Optional[str] = Field(default=None, description="识别到的意图")
    sources: list[str] = Field(default_factory=list, description="引用来源")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class DetectResponse(BaseModel):
    """隐患识别响应。"""

    answer: str = Field(..., description="Markdown 格式结果（定级 + 整改方案）")
    hazard_level: Optional[str] = Field(default=None, description="隐患等级")
    detections: list[dict[str, Any]] = Field(default_factory=list, description="CV 检测目标")
    sources: list[str] = Field(default_factory=list, description="引用来源")


class PermitResponse(BaseModel):
    """作业票审核响应。"""

    answer: str = Field(..., description="Markdown 格式审核结论")
    passed: Optional[bool] = Field(default=None, description="是否审核通过")
    missing_fields: list[str] = Field(default_factory=list, description="缺失字段")
    issues: list[str] = Field(default_factory=list, description="合规问题列表")
    permit_info: Optional[dict[str, Any]] = Field(default=None, description="匹配到的作业票规范（GB 30871-2022 依据）")
