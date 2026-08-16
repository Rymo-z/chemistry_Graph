"""知识抽取层：定义实体类型与关系类型（统一 schema）。

图数据库中所有节点统一用 `Entity` 标签，通过 `type` 属性区分类型，
关系类型为固定的枚举集合，保证知识图谱语义可控、可复用。
"""
from __future__ import annotations

from enum import Enum


class EntityType(str, Enum):
    """实体类型（图节点 type 属性的取值）。"""

    REGULATION = "Regulation"          # 法规 / 规章
    STANDARD = "Standard"              # 技术标准
    HAZARD = "Hazard"                  # 隐患
    EQUIPMENT = "Equipment"            # 设备设施
    OPERATION = "Operation"            # 作业类型（如高处作业）
    MATERIAL = "Material"              # 危险物质
    LOCATION = "Location"              # 场所 / 区域
    PERSON_ROLE = "PersonRole"         # 人员角色 / 岗位
    QUALIFICATION = "Qualification"    # 资质 / 证书
    PERMIT = "Permit"                  # 作业票 / 许可证
    PROCESS = "Process"                # 工艺过程
    ACCIDENT = "Accident"              # 事故案例
    DOCUMENT = "Document"              # 文件 / 制度


class RelationType(str, Enum):
    """关系类型（图中关系 type 属性的取值）。"""

    REGULATES = "REGULATES"                              # (Regulation) 规范 (X)
    REQUIRES = "REQUIRES"                                # (Operation) 要求/需要 (Permit|Qualification|Measure)
    HAS_PERMIT = "HAS_PERMIT"                            # (Operation|Equipment) 需要 (Permit)
    INVOLVES = "INVOLVES"                                # (Operation) 涉及 (Equipment|Material|Hazard)
    PROHIBITS = "PROHIBITS"                              # (Regulation) 禁止 (X)
    HAS_HAZARD = "HAS_HAZARD"                            # (Equipment|Location) 存在 (Hazard)
    LOCATED_IN = "LOCATED_IN"                            # (Equipment|Hazard) 位于 (Location)
    CAUSED_BY = "CAUSED_BY"                              # (Accident|Hazard) 由 (X) 导致
    RESULTS_IN = "RESULTS_IN"                            # (X) 导致 (Accident|Hazard)
    REQUIRES_QUALIFICATION = "REQUIRES_QUALIFICATION"    # (Operation) 需要 (Qualification)
    VIOLATES = "VIOLATES"                                # (X) 违反 (Regulation)
    PREVENTS = "PREVENTS"                                # (Regulation|Standard) 预防 (Hazard)
    MENTIONS = "MENTIONS"                                # (Accident) 提及 (Equipment|Operation|Material)
    BELONGS_TO = "BELONGS_TO"                            # (Hazard) 属于 (Hazard|Category)


class HazardLevel(str, Enum):
    """隐患等级（依据 重大/一般 隐患判定原则）。"""

    CRITICAL = "特别重大隐患"
    MAJOR = "重大隐患"
    GENERAL = "一般隐患"


# 供提示词注入的枚举说明
ENTITY_TYPE_VALUES: list[str] = [e.value for e in EntityType]
RELATION_TYPE_VALUES: list[str] = [r.value for r in RelationType]
