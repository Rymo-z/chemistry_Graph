"""知识抽取层：从文本抽取实体与关系。"""

from _002_extract_information.schema import EntityType, HazardLevel, RelationType
from _002_extract_information.extractor_base import BaseExtractor

__all__ = ["EntityType", "RelationType", "HazardLevel", "BaseExtractor"]
