"""
ai_module/kg/entities.py

Dataclass định nghĩa các entity dùng trong KG pipeline.
Tách riêng khỏi entity_extractor.py và graph_builder.py
để tránh circular import.

Import pattern đúng:
    entity_extractor.py  → from ai_module.kg.entities import ...
    graph_builder.py     → from ai_module.kg.entities import ...
    relation_extractor.py→ from ai_module.kg.entities import ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# SHARED UTILS — dùng chung cho entity_extractor, relation_extractor, graph_builder
# =============================================================================

def normalize_entity_name(name: str) -> str:
    """
    Chuẩn hoá tên entity để dedup cross-module.
    Strip dấu gạch ngang, gạch dưới, khoảng trắng → lowercase key.
    VD: "pho-bert" → "phobert", "BiLSTM_CRF" → "bilstmcrf"

    Public (không có dấu _) để các module khác import tự do.
    """
    return re.sub(r"[-_\s]", "", name).lower()


# =============================================================================
# ENTITY DATACLASSES
# Mỗi dataclass tương ứng với 1 node type trong Neo4j schema.
# =============================================================================

@dataclass
class AuthorEntity:
    """
    Tương ứng node :Author trong Neo4j.
    id sẽ được sinh bởi graph_builder khi MERGE vào Neo4j.
    """
    name:             str
    affiliation:      Optional[str] = None   # raw string, trước khi link sang Institution
    email:            Optional[str] = None
    country:          Optional[str] = None   # "VN" | "US" | ...
    institution_type: Optional[str] = None   # "university" | "institute" | "company" | "other"


@dataclass
class MethodEntity:
    """
    Tương ứng node :Method trong Neo4j.
    aliases được lưu dạng list[str] ở tầng Python;
    graph_builder sẽ join thành "alias1|alias2" (aliases_text) trước khi SET vào Neo4j.
    """
    name:           str
    category:       Optional[str]  = None    # "pretrained_lm" | "sequence_labeling" | ...
    aliases:        list[str]      = field(default_factory=list)
    based_on:       list[str]      = field(default_factory=list)  # tên method cha
    source_paper:   Optional[str]  = None    # doc_id của paper nguồn
    source_section: Optional[str]  = None    # "method" | "abstract" | ...
    confidence:     float          = 0.80
    evidence:       str            = ""      # câu văn gốc, tối đa 200 chars


@dataclass
class DatasetEntity:
    """
    Tương ứng node :Dataset trong Neo4j.
    """
    name:           str
    language:       Optional[str]  = None    # "vi" | "en" | "multilingual"
    aliases:        list[str]      = field(default_factory=list)
    metric:         Optional[str]  = None    # VD: "F1=92.3"
    source_paper:   Optional[str]  = None
    source_section: Optional[str]  = None
    confidence:     float          = 0.80
    evidence:       str            = ""


@dataclass
class TaskEntity:
    """
    Tương ứng node :Task trong Neo4j.
    """
    name:           str
    source_paper:   Optional[str]  = None
    source_section: Optional[str]  = None
    confidence:     float          = 0.80
    evidence:       str            = ""


@dataclass
class ExtractedEntities:
    """
    Container kết quả của EntityExtractor.extract().
    graph_builder nhận object này để build KG.
    """
    authors:  list[AuthorEntity]  = field(default_factory=list)
    methods:  list[MethodEntity]  = field(default_factory=list)
    datasets: list[DatasetEntity] = field(default_factory=list)
    tasks:    list[TaskEntity]    = field(default_factory=list)

    def is_empty(self) -> bool:
        """True nếu không extract được entity nào."""
        return not (self.authors or self.methods or self.datasets or self.tasks)

    def summary(self) -> str:
        """Log-friendly summary."""
        return (
            f"authors={len(self.authors)} "
            f"methods={len(self.methods)} "
            f"datasets={len(self.datasets)} "
            f"tasks={len(self.tasks)}"
        )
