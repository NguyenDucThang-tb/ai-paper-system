"""
ai_module/kg/graph_updater.py

Cập nhật Knowledge Graph sau khi đã build xong (graph_builder.py).
Trong khi graph_builder.py chỉ INSERT lần đầu, graph_updater.py xử lý:

    1. EntityMerger      — gộp các node trùng nhau (alias dedup, fuzzy match)
    2. ProvenanceUpdater — cập nhật source_paper, source_section, confidence
                           khi cùng 1 entity xuất hiện ở nhiều paper
    3. ConsistencyChecker— phát hiện conflict, inverse-edge duplicate,
                           entity không có evidence

Thứ tự khuyến nghị khi chạy:
    updater = GraphUpdater(neo4j_client)
    updater.run_all(paper_id)           # chạy cả 3 bước theo đúng thứ tự

Hoặc từng bước riêng:
    updater.merge_entities(paper_id)
    updater.update_provenance(paper_id)
    updater.check_consistency(paper_id)

Requires:
    - graph_builder.py đã chạy xong (paper.processing_status = 'kg_built')
    - neo4j_client cung cấp đủ các method theo Neo4jClientProtocol bên dưới

Changelog:
    v2 — 2025-05
        [fix-1] Import ExtractedEntities và entity classes từ entities.py thay vì
                graph_builder.py — graph_builder không định nghĩa các class này,
                chỉ re-export ngầm → coupling dễ vỡ khi graph_builder thay đổi
        [fix-2] APOC availability guard trong EntityMerger.__init__:
                kiểm tra apoc.refactor.mergeNodes trước khi dùng,
                fallback graceful nếu APOC không có (Neo4j Community Edition)
        [fix-3] ProvenanceUpdater._update_method/dataset/task_edge dùng
                confidence-aware SET — chỉ overwrite evidence khi confidence
                mới >= hiện tại, nhất quán với ON MATCH SET trong neo4j_client
        [fix-4] Thêm _normalize_name re-export từ entities.py thay vì
                định nghĩa lại — tránh diverge logic normalize
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from ingestion.schema.document_schema import UnifiedDocument

# [fix-1] Import trực tiếp từ entities.py — nguồn của sự thật duy nhất
# graph_builder.py không định nghĩa các class này, chỉ re-export ngầm
# → dễ vỡ nếu graph_builder thay đổi import structure
from ai_module.kg.entities import (
    ExtractedEntities,
    MethodEntity,
    DatasetEntity,
    TaskEntity,
    normalize_entity_name,  # [fix-4] dùng chung, không định nghĩa lại
)

logger = logging.getLogger(__name__)


# =============================================================================
# NEO4J CLIENT PROTOCOL
# Định nghĩa tập method tối thiểu graph_updater cần từ Neo4jClient.
# Dùng Protocol để dễ mock trong test, không phụ thuộc import vòng tròn.
# =============================================================================

@runtime_checkable
class Neo4jClientProtocol(Protocol):

    def run_query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Chạy Cypher query, trả về list[dict] rows."""
        ...

    def lookup_method_by_fulltext(
        self, name: str, threshold: float = 0.75
    ) -> Optional[str]:
        """
        Tìm Method node gần đúng theo name + aliases_text.
        Trả về node name nếu tìm thấy, None nếu không.
        """
        ...

    def lookup_dataset_by_fulltext(
        self, name: str, threshold: float = 0.75
    ) -> Optional[str]:
        """Tương tự lookup_method nhưng cho Dataset."""
        ...

    def get_paper_by_id(self, paper_id: str) -> Optional[dict]:
        """Trả về Paper node properties theo id."""
        ...

    def set_paper_status(self, paper_id: str, status: str) -> None:
        """Cập nhật processing_status của Paper node."""
        ...


# =============================================================================
# VALUE OBJECTS — kết quả từ từng bước
# =============================================================================

@dataclass
class MergeResult:
    """Kết quả sau EntityMerger.merge_entities()."""
    paper_id: str
    methods_merged: int = 0     # số cặp Method node được gộp
    datasets_merged: int = 0
    tasks_merged: int = 0
    aliases_registered: int = 0 # số alias mới được thêm vào aliases_text
    apoc_available: bool = True  # [fix-2] False nếu APOC không có


@dataclass
class ProvenanceUpdate:
    """1 lần cập nhật provenance trên 1 edge."""
    node_type: str          # "Method" | "Dataset" | "Task"
    node_name: str
    paper_id: str
    source_section: str
    confidence: float
    evidence: str


@dataclass
class ConsistencyIssue:
    """1 vấn đề phát hiện bởi ConsistencyChecker."""
    issue_type: str         # xem _ISSUE_TYPES bên dưới
    description: str
    node_type: str = ""
    node_name: str = ""
    paper_id: str = ""
    severity: str = "warning"  # "warning" | "error"


_ISSUE_TYPES = {
    "DUPLICATE_EDGE":    "Duplicate edge giữa 2 node",
    "INVERSE_EDGE":      "Edge thuận và nghịch cùng tồn tại",
    "NO_EVIDENCE":       "Entity có confidence > 0 nhưng không có evidence",
    "ORPHAN_METHOD":     "Method không có Paper nào link đến",
    "ORPHAN_DATASET":    "Dataset không có Paper nào link đến",
    "LOW_CONFIDENCE":    "Edge confidence dưới ngưỡng tối thiểu",
}


# =============================================================================
# HELPERS — dùng chung giữa các class
# =============================================================================

# [fix-4] Alias _normalize_name → normalize_entity_name từ entities.py
# Không định nghĩa lại để tránh logic diverge giữa extractor và updater
_normalize_name = normalize_entity_name


def _aliases_to_text(aliases: list[str]) -> str:
    """
    Chuyển list alias → pipe-separated string để lưu vào Neo4j.
    Neo4j full-text index chỉ hoạt động trên STRING, không phải list.
    VD: ["PhoBERT", "pho-bert"] → "phobert|pho-bert"
    """
    return "|".join(a.strip() for a in aliases if a.strip())


def _text_to_aliases(aliases_text: str) -> list[str]:
    """Ngược lại với _aliases_to_text."""
    if not aliases_text:
        return []
    return [a.strip() for a in aliases_text.split("|") if a.strip()]


# =============================================================================
# ENTITY MERGER
# Gộp các node trùng nhau sau khi LLM extract từ nhiều section / nhiều paper.
# =============================================================================

class EntityMerger:
    """
    Phát hiện và gộp entity node trùng nhau trong Neo4j.

    Vấn đề cần giải quyết:
        - entity_extractor chạy per-section → có thể tạo Method node "phobert"
          và "pho-bert" riêng biệt nếu 2 section dùng tên khác nhau
        - graph_builder dùng MERGE (m:Method {name: $name}) → exact match,
          không bắt được alias

    Cách hoạt động:
        1. Lấy tất cả entity của paper vừa build
        2. Với mỗi entity, tìm node có normalized name trùng hoặc fulltext match
        3. Nếu tìm thấy node khác đã tồn tại → merge (redirect edges + delete duplicate)
        4. Nếu không → đăng ký alias vào aliases_text để tìm lần sau

    [fix-2] APOC guard:
        apoc.refactor.mergeNodes yêu cầu APOC plugin — không có sẵn trong
        Neo4j Community Edition. EntityMerger kiểm tra APOC khi khởi tạo.
        Nếu không có APOC: skip merge node (chỉ đăng ký alias), log warning 1 lần.
        Không raise exception — pipeline vẫn chạy được, chỉ mất tính năng dedup.
    """

    _MERGE_METHOD_CYPHER = """
        MATCH (old:Method {name: $old_name})
        MATCH (new:Method {name: $new_name})
        WHERE old <> new
        // Redirect tất cả edge từ Paper vào old → new
        CALL apoc.refactor.mergeNodes([old, new], {
            properties: 'combine',
            mergeRels: true
        }) YIELD node
        SET node.name = $canonical_name
        RETURN node.name AS merged
    """

    _MERGE_DATASET_CYPHER = """
        MATCH (old:Dataset {name: $old_name})
        MATCH (new:Dataset {name: $new_name})
        WHERE old <> new
        CALL apoc.refactor.mergeNodes([old, new], {
            properties: 'combine',
            mergeRels: true
        }) YIELD node
        SET node.name = $canonical_name
        RETURN node.name AS merged
    """

    _UPDATE_ALIASES_CYPHER = """
        MATCH (n:{label} {{name: $name}})
        SET n.aliases_text = CASE
            WHEN n.aliases_text IS NULL OR n.aliases_text = ''
                THEN $new_aliases
            WHEN NOT $new_aliases IN split(n.aliases_text, '|')
                THEN n.aliases_text + '|' + $new_aliases
            ELSE n.aliases_text
        END
        RETURN n.name AS name, n.aliases_text AS aliases_text
    """

    # Query kiểm tra APOC có available không  [fix-2]
    _CHECK_APOC_CYPHER = """
        CALL apoc.help('refactor') YIELD name
        WHERE name = 'apoc.refactor.mergeNodes'
        RETURN count(*) AS cnt
    """

    def __init__(self, client: Neo4jClientProtocol) -> None:
        self._client = client
        self._apoc_available = self._check_apoc()  # [fix-2]

    def _check_apoc(self) -> bool:
        """
        Kiểm tra APOC plugin có available không.  [fix-2]
        Trả về True nếu có, False nếu không (Neo4j Community / thiếu plugin).
        Chỉ log warning 1 lần khi khởi tạo — không spam per-call.
        """
        try:
            rows = self._client.run_query(self._CHECK_APOC_CYPHER)
            available = bool(rows and rows[0].get("cnt", 0) > 0)
            if not available:
                logger.warning(
                    "EntityMerger: APOC plugin không available "
                    "(apoc.refactor.mergeNodes không tìm thấy). "
                    "Node merge sẽ bị skip — chỉ alias registration được thực hiện. "
                    "Để enable APOC: thêm APOC jar vào Neo4j plugins/ directory."
                )
            else:
                logger.debug("EntityMerger: APOC available — node merge enabled.")
            return available
        except Exception as e:
            logger.warning(
                "EntityMerger: không thể kiểm tra APOC availability (%s). "
                "Giả định APOC không có — node merge bị skip.",
                e,
            )
            return False

    def merge_entities(
        self,
        paper_id: str,
        entities: ExtractedEntities,
    ) -> MergeResult:
        """
        Gộp entity duplicate cho 1 paper vừa build.

        Thứ tự:
            1. Method merge
            2. Dataset merge
            3. Task merge (ít xảy ra duplicate hơn vì tên task chuẩn)
        """
        result = MergeResult(paper_id=paper_id, apoc_available=self._apoc_available)

        result.methods_merged, result.aliases_registered = self._merge_entity_list(
            entities=entities.methods,
            lookup_fn=self._client.lookup_method_by_fulltext,
            merge_cypher=self._MERGE_METHOD_CYPHER,
            label="Method",
        )

        result.datasets_merged, aliases_ds = self._merge_entity_list(
            entities=entities.datasets,
            lookup_fn=self._client.lookup_dataset_by_fulltext,
            merge_cypher=self._MERGE_DATASET_CYPHER,
            label="Dataset",
        )
        result.aliases_registered += aliases_ds

        # Task: không merge node (tên task đã canonical), chỉ đăng ký alias
        for task in entities.tasks:
            if _normalize_name(task.name) != task.name:
                self._register_alias(label="Task", canonical=task.name, alias=task.name)
                result.aliases_registered += 1

        logger.info(
            "EntityMerger: paper_id=%s methods_merged=%d datasets_merged=%d "
            "aliases=%d apoc=%s",
            paper_id,
            result.methods_merged,
            result.datasets_merged,
            result.aliases_registered,
            "yes" if self._apoc_available else "no (skip merge)",
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _merge_entity_list(
        self,
        entities: list,
        lookup_fn,
        merge_cypher: str,
        label: str,
    ) -> tuple[int, int]:
        """
        Với mỗi entity trong list:
            - Lookup fulltext → tìm node có name/alias tương tự
            - Nếu tìm thấy node KHÁC:
                - APOC available  → merge 2 node lại (redirect edges)
                - APOC không có   → skip merge, chỉ log debug  [fix-2]
            - Nếu không → đăng ký alias mới vào aliases_text

        Returns:
            (merged_count, alias_registered_count)
        """
        merged = 0
        aliases = 0
        seen_normalized: set[str] = set()

        for entity in entities:
            norm = _normalize_name(entity.name)
            if norm in seen_normalized:
                continue
            seen_normalized.add(norm)

            existing_name = lookup_fn(entity.name, threshold=0.75)

            if existing_name and existing_name != entity.name:
                # [fix-2] Chỉ merge nếu APOC available
                if self._apoc_available:
                    try:
                        self._client.run_query(
                            merge_cypher,
                            params={
                                "old_name":       entity.name,
                                "new_name":       existing_name,
                                "canonical_name": existing_name,
                            },
                        )
                        merged += 1
                        logger.debug(
                            "EntityMerger._merge_entity_list[%s]: merged '%s' → '%s'",
                            label, entity.name, existing_name,
                        )
                    except Exception:
                        logger.exception(
                            "EntityMerger: merge thất bại '%s' → '%s' — bỏ qua",
                            entity.name, existing_name,
                        )
                else:
                    # [fix-2] APOC không có — đăng ký alias thay thế để
                    # fulltext search vẫn tìm được entity qua cả 2 tên
                    logger.debug(
                        "EntityMerger[%s]: APOC skip — đăng ký '%s' là alias của '%s'",
                        label, entity.name, existing_name,
                    )
                    self._register_alias(
                        label=label,
                        canonical=existing_name,
                        alias=entity.name,
                    )
                    aliases += 1
            else:
                # Không có node match → đăng ký alias để tìm lần sau
                for alias in getattr(entity, "aliases", []):
                    if alias and _normalize_name(alias) != norm:
                        self._register_alias(label=label, canonical=entity.name, alias=alias)
                        aliases += 1

        return merged, aliases

    def _register_alias(self, label: str, canonical: str, alias: str) -> None:
        """Thêm alias vào aliases_text của node, tránh duplicate."""
        cypher = self._UPDATE_ALIASES_CYPHER.format(label=label)
        try:
            self._client.run_query(
                cypher,
                params={"name": canonical, "new_aliases": alias.strip()},
            )
        except Exception:
            logger.warning(
                "EntityMerger._register_alias: thất bại label=%s name=%s alias=%s",
                label, canonical, alias,
            )


# =============================================================================
# PROVENANCE UPDATER
# Cập nhật source_paper, source_section, confidence trên các edges
# khi cùng 1 entity xuất hiện ở nhiều paper.
# =============================================================================

class ProvenanceUpdater:
    """
    Đảm bảo mỗi edge (Paper)-[r]->(Entity) có đủ provenance:
        r.source_paper   — paper_id của paper đang build
        r.source_section — section extract được ("method", "experiment", ...)
        r.confidence     — float 0.0 → 1.0
        r.evidence       — câu văn gốc, max 200 chars

    [fix-3] Confidence-aware SET:
        Thay vì force-overwrite evidence bất kể confidence,
        chỉ update evidence khi confidence mới >= hiện tại.
        Nhất quán với ON MATCH SET logic trong neo4j_client.py.
        Lý do: nếu paper B ingest sau paper A với confidence thấp hơn,
        evidence tốt của A không bị mất.
    """

    # [fix-3] Dùng CASE WHEN để chỉ overwrite evidence khi confidence mới cao hơn
    _UPDATE_METHOD_EDGE = """
        MATCH (p:Paper {id: $paper_id})-[r:USES_METHOD]->(m:Method {name: $method_name})
        SET r.source_paper   = $source_paper,
            r.source_section = $source_section,
            r.confidence     = CASE WHEN $confidence >= r.confidence
                               THEN $confidence ELSE r.confidence END,
            r.evidence       = CASE WHEN $confidence >= r.confidence
                               THEN $evidence ELSE r.evidence END
        RETURN r.confidence AS confidence
    """

    # [fix-3] Tương tự cho EVALUATES_ON
    _UPDATE_DATASET_EDGE = """
        MATCH (p:Paper {id: $paper_id})-[r:EVALUATES_ON]->(d:Dataset {name: $dataset_name})
        SET r.source_paper   = $source_paper,
            r.source_section = $source_section,
            r.confidence     = CASE WHEN $confidence >= r.confidence
                               THEN $confidence ELSE r.confidence END,
            r.evidence       = CASE WHEN $confidence >= r.confidence
                               THEN $evidence ELSE r.evidence END,
            r.metric         = $metric
        RETURN r.confidence AS confidence
    """

    # [fix-3] Tương tự cho ADDRESSES_TASK
    _UPDATE_TASK_EDGE = """
        MATCH (p:Paper {id: $paper_id})-[r:ADDRESSES_TASK]->(t:Task {name: $task_name})
        SET r.source_paper   = $source_paper,
            r.source_section = $source_section,
            r.confidence     = CASE WHEN $confidence >= r.confidence
                               THEN $confidence ELSE r.confidence END,
            r.evidence       = CASE WHEN $confidence >= r.confidence
                               THEN $evidence ELSE r.evidence END
        RETURN r.confidence AS confidence
    """

    def __init__(self, client: Neo4jClientProtocol) -> None:
        self._client = client

    def update_provenance(
        self,
        paper_id: str,
        entities: ExtractedEntities,
    ) -> list[ProvenanceUpdate]:
        """
        Update provenance trên tất cả edges của paper_id.
        Gọi sau EntityMerger để merge đã xong trước khi set provenance.

        [fix-3] Chỉ overwrite evidence khi confidence mới >= hiện tại.

        Returns:
            list[ProvenanceUpdate] — log các update đã thực hiện
        """
        updates: list[ProvenanceUpdate] = []

        for method in entities.methods:
            ok = self._update_edge(
                cypher=self._UPDATE_METHOD_EDGE,
                params={
                    "paper_id":       paper_id,
                    "method_name":    method.name,
                    "source_paper":   paper_id,
                    "source_section": method.source_section,
                    "confidence":     method.confidence,
                    "evidence":       (method.evidence or "")[:200],
                },
            )
            if ok:
                updates.append(ProvenanceUpdate(
                    node_type="Method",
                    node_name=method.name,
                    paper_id=paper_id,
                    source_section=method.source_section,
                    confidence=method.confidence,
                    evidence=method.evidence,
                ))

        for dataset in entities.datasets:
            ok = self._update_edge(
                cypher=self._UPDATE_DATASET_EDGE,
                params={
                    "paper_id":       paper_id,
                    "dataset_name":   dataset.name,
                    "source_paper":   paper_id,
                    "source_section": dataset.source_section,
                    "confidence":     dataset.confidence,
                    "evidence":       (dataset.evidence or "")[:200],
                    "metric":         dataset.metric,
                },
            )
            if ok:
                updates.append(ProvenanceUpdate(
                    node_type="Dataset",
                    node_name=dataset.name,
                    paper_id=paper_id,
                    source_section=dataset.source_section,
                    confidence=dataset.confidence,
                    evidence=dataset.evidence,
                ))

        for task in entities.tasks:
            ok = self._update_edge(
                cypher=self._UPDATE_TASK_EDGE,
                params={
                    "paper_id":       paper_id,
                    "task_name":      task.name,
                    "source_paper":   paper_id,
                    "source_section": task.source_section,
                    "confidence":     task.confidence,
                    "evidence":       (task.evidence or "")[:200],
                },
            )
            if ok:
                updates.append(ProvenanceUpdate(
                    node_type="Task",
                    node_name=task.name,
                    paper_id=paper_id,
                    source_section=task.source_section,
                    confidence=task.confidence,
                    evidence=task.evidence,
                ))

        logger.info(
            "ProvenanceUpdater: paper_id=%s updated %d edges",
            paper_id, len(updates),
        )
        return updates

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _update_edge(self, cypher: str, params: dict) -> bool:
        """
        Chạy update cypher. Trả về True nếu có ít nhất 1 row được update.
        """
        try:
            rows = self._client.run_query(cypher, params)
            return bool(rows)
        except Exception:
            logger.exception(
                "ProvenanceUpdater._update_edge: thất bại params=%s",
                {k: v for k, v in params.items() if k != "evidence"},
            )
            return False


# =============================================================================
# CONSISTENCY CHECKER
# Phát hiện các vấn đề trong graph sau khi build + merge + provenance update.
# =============================================================================

class ConsistencyChecker:
    """
    Kiểm tra tính nhất quán của graph sau khi build.

    Các loại vấn đề được kiểm tra:
        1. DUPLICATE_EDGE    — cùng (Paper, Method) có 2+ edge USES_METHOD
        2. INVERSE_EDGE      — Method A BASED_ON B và B BASED_ON A cùng tồn tại
        3. NO_EVIDENCE       — edge có confidence > 0.5 nhưng evidence rỗng
        4. ORPHAN_METHOD     — Method không có Paper nào link đến
        5. ORPHAN_DATASET    — Dataset không có Paper nào link đến
        6. LOW_CONFIDENCE    — edge confidence < min_confidence

    Không auto-fix — chỉ report để người dùng quyết định.
    """

    _CHECK_DUPLICATE_METHOD_EDGE = """
        MATCH (p:Paper {id: $paper_id})-[r:USES_METHOD]->(m:Method)
        WITH p, m, count(r) AS cnt
        WHERE cnt > 1
        RETURN m.name AS name, cnt
    """

    _CHECK_DUPLICATE_DATASET_EDGE = """
        MATCH (p:Paper {id: $paper_id})-[r:EVALUATES_ON]->(d:Dataset)
        WITH p, d, count(r) AS cnt
        WHERE cnt > 1
        RETURN d.name AS name, cnt
    """

    _CHECK_INVERSE_BASED_ON = """
        MATCH (a:Method)-[:BASED_ON]->(b:Method)-[:BASED_ON]->(a)
        RETURN a.name AS method_a, b.name AS method_b
        LIMIT 50
    """

    _CHECK_NO_EVIDENCE_METHOD = """
        MATCH (p:Paper {id: $paper_id})-[r:USES_METHOD]->(m:Method)
        WHERE r.confidence > $confidence_threshold
          AND (r.evidence IS NULL OR r.evidence = '')
        RETURN m.name AS name, r.confidence AS confidence
    """

    _CHECK_NO_EVIDENCE_DATASET = """
        MATCH (p:Paper {id: $paper_id})-[r:EVALUATES_ON]->(d:Dataset)
        WHERE r.confidence > $confidence_threshold
          AND (r.evidence IS NULL OR r.evidence = '')
        RETURN d.name AS name, r.confidence AS confidence
    """

    _CHECK_ORPHAN_METHOD = """
        MATCH (m:Method)
        WHERE NOT EXISTS { (p:Paper)-[:USES_METHOD]->(m) }
        RETURN m.name AS name
        LIMIT 100
    """

    _CHECK_ORPHAN_DATASET = """
        MATCH (d:Dataset)
        WHERE NOT EXISTS { (p:Paper)-[:EVALUATES_ON]->(d) }
        RETURN d.name AS name
        LIMIT 100
    """

    _CHECK_LOW_CONFIDENCE_METHOD = """
        MATCH (p:Paper {id: $paper_id})-[r:USES_METHOD]->(m:Method)
        WHERE r.confidence < $min_confidence
        RETURN m.name AS name, r.confidence AS confidence
    """

    def __init__(
        self,
        client: Neo4jClientProtocol,
        min_confidence: float = 0.5,
        evidence_confidence_threshold: float = 0.75,
    ) -> None:
        self._client = client
        self._min_confidence = min_confidence
        self._evidence_threshold = evidence_confidence_threshold

    def check_consistency(
        self,
        paper_id: str,
        check_orphans: bool = False,
    ) -> list[ConsistencyIssue]:
        """
        Chạy tất cả consistency check cho paper_id.

        Args:
            paper_id:      ID của paper cần kiểm tra
            check_orphans: Có kiểm tra orphan node không.
                           Tắt mặc định vì orphan check là global query,
                           tốn kém nếu gọi cho mỗi paper.
                           Chỉ bật khi chạy maintenance job định kỳ.
        """
        issues: list[ConsistencyIssue] = []

        issues.extend(self._check_duplicate_edges(paper_id))
        issues.extend(self._check_inverse_based_on())
        issues.extend(self._check_no_evidence(paper_id))
        issues.extend(self._check_low_confidence(paper_id))

        if check_orphans:
            issues.extend(self._check_orphans())

        if issues:
            error_count   = sum(1 for i in issues if i.severity == "error")
            warning_count = sum(1 for i in issues if i.severity == "warning")
            logger.warning(
                "ConsistencyChecker: paper_id=%s — %d issues (error=%d warning=%d)",
                paper_id, len(issues), error_count, warning_count,
            )
        else:
            logger.info("ConsistencyChecker: paper_id=%s — OK, no issues", paper_id)

        return issues

    # ------------------------------------------------------------------
    # Private check methods
    # ------------------------------------------------------------------

    def _check_duplicate_edges(self, paper_id: str) -> list[ConsistencyIssue]:
        issues = []
        params = {"paper_id": paper_id}

        for cypher, node_type in [
            (self._CHECK_DUPLICATE_METHOD_EDGE,  "Method"),
            (self._CHECK_DUPLICATE_DATASET_EDGE, "Dataset"),
        ]:
            try:
                rows = self._client.run_query(cypher, params)
                for row in rows:
                    issues.append(ConsistencyIssue(
                        issue_type="DUPLICATE_EDGE",
                        description=f"{node_type} '{row.get('name', '?')}' có {row.get('cnt', '?')} edge từ cùng paper",
                        node_type=node_type,
                        node_name=row.get("name", ""),
                        paper_id=paper_id,
                        severity="error",
                    ))
            except Exception:
                logger.exception(
                    "ConsistencyChecker._check_duplicate_edges: query thất bại node_type=%s",
                    node_type,
                )
        return issues

    def _check_inverse_based_on(self) -> list[ConsistencyIssue]:
        issues = []
        try:
            rows = self._client.run_query(self._CHECK_INVERSE_BASED_ON)
            for row in rows:
                issues.append(ConsistencyIssue(
                    issue_type="INVERSE_EDGE",
                    description=(
                        f"Method BASED_ON cycle: '{row['method_a']}' ↔ '{row['method_b']}'"
                    ),
                    node_type="Method",
                    node_name=row["method_a"],
                    severity="error",
                ))
        except Exception:
            logger.exception("ConsistencyChecker._check_inverse_based_on: query thất bại")
        return issues

    def _check_no_evidence(self, paper_id: str) -> list[ConsistencyIssue]:
        issues = []
        params = {
            "paper_id": paper_id,
            "confidence_threshold": self._evidence_threshold,
        }

        for cypher, node_type in [
            (self._CHECK_NO_EVIDENCE_METHOD,  "Method"),
            (self._CHECK_NO_EVIDENCE_DATASET, "Dataset"),
        ]:
            try:
                rows = self._client.run_query(cypher, params)
                for row in rows:
                    issues.append(ConsistencyIssue(
                        issue_type="NO_EVIDENCE",
                        description=(
                            f"{node_type} '{row.get('name', '?')}' "
                            f"confidence={row.get('confidence', 0):.2f} nhưng không có evidence"
                        ),
                        node_type=node_type,
                        node_name=row.get("name", ""),
                        paper_id=paper_id,
                        severity="warning",
                    ))
            except Exception:
                logger.exception(
                    "ConsistencyChecker._check_no_evidence: query thất bại node_type=%s",
                    node_type,
                )
        return issues

    def _check_low_confidence(self, paper_id: str) -> list[ConsistencyIssue]:
        issues = []
        params = {
            "paper_id": paper_id,
            "min_confidence": self._min_confidence,
        }
        try:
            rows = self._client.run_query(self._CHECK_LOW_CONFIDENCE_METHOD, params)
            for row in rows:
                issues.append(ConsistencyIssue(
                    issue_type="LOW_CONFIDENCE",
                    description=(
                        f"Method '{row['name']}' confidence={row['confidence']:.2f} "
                        f"< threshold={self._min_confidence}"
                    ),
                    node_type="Method",
                    node_name=row["name"],
                    paper_id=paper_id,
                    severity="warning",
                ))
        except Exception:
            logger.exception("ConsistencyChecker._check_low_confidence: query thất bại")
        return issues

    def _check_orphans(self) -> list[ConsistencyIssue]:
        """Global query — chỉ gọi từ maintenance job, không phải per-paper."""
        issues = []
        for cypher, node_type, issue_type in [
            (self._CHECK_ORPHAN_METHOD,  "Method",  "ORPHAN_METHOD"),
            (self._CHECK_ORPHAN_DATASET, "Dataset", "ORPHAN_DATASET"),
        ]:
            try:
                rows = self._client.run_query(cypher)
                for row in rows:
                    issues.append(ConsistencyIssue(
                        issue_type=issue_type,
                        description=f"{node_type} '{row.get('name', '?')}' không có Paper nào link đến",
                        node_type=node_type,
                        node_name=row.get("name", ""),
                        severity="warning",
                    ))
            except Exception:
                logger.exception(
                    "ConsistencyChecker._check_orphans: query thất bại node_type=%s",
                    node_type,
                )
        return issues


# =============================================================================
# GRAPH UPDATER — Orchestrator
# =============================================================================

@dataclass
class UpdateReport:
    """Tổng hợp kết quả sau run_all()."""
    paper_id: str
    merge_result: Optional[MergeResult] = None
    provenance_updates: list[ProvenanceUpdate] = field(default_factory=list)
    consistency_issues: list[ConsistencyIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.consistency_issues)

    @property
    def summary(self) -> str:
        m = self.merge_result
        merge_str = (
            f"methods_merged={m.methods_merged} "
            f"datasets_merged={m.datasets_merged} "
            f"aliases={m.aliases_registered} "
            f"apoc={'yes' if m.apoc_available else 'no'}"
        ) if m else "merge=skipped"
        return (
            f"paper_id={self.paper_id} | "
            f"{merge_str} | "
            f"provenance_updates={len(self.provenance_updates)} | "
            f"issues={len(self.consistency_issues)} "
            f"(errors={sum(1 for i in self.consistency_issues if i.severity == 'error')})"
        )


class GraphUpdater:
    """
    Orchestrator chạy đầy đủ update flow cho 1 paper sau build.

    Cách dùng:
        updater = GraphUpdater(neo4j_client)

        # Sau khi GraphBuilder.build() xong:
        report = updater.run_all(paper_id, entities)
        if report.has_errors:
            logger.error(report.summary)

    Hoặc từng bước:
        updater.merge_entities(paper_id, entities)
        updater.update_provenance(paper_id, entities)
        issues = updater.check_consistency(paper_id)
    """

    def __init__(
        self,
        client: Neo4jClientProtocol,
        min_confidence: float = 0.5,
        evidence_confidence_threshold: float = 0.75,
    ) -> None:
        self._client = client
        self._merger   = EntityMerger(client)
        self._prov     = ProvenanceUpdater(client)
        self._checker  = ConsistencyChecker(
            client,
            min_confidence=min_confidence,
            evidence_confidence_threshold=evidence_confidence_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(
        self,
        paper_id: str,
        entities: ExtractedEntities,
        check_orphans: bool = False,
    ) -> UpdateReport:
        """
        Chạy đầy đủ: merge → provenance → consistency.
        Thứ tự này là bắt buộc:
            1. Merge trước để không có duplicate node
            2. Provenance sau merge để edge trỏ đúng canonical node
            3. Consistency sau cùng để kiểm tra kết quả
        """
        report = UpdateReport(paper_id=paper_id)
        logger.info("GraphUpdater.run_all: start paper_id=%s", paper_id)

        try:
            report.merge_result = self._merger.merge_entities(paper_id, entities)
        except Exception:
            logger.exception("GraphUpdater: EntityMerger thất bại paper_id=%s", paper_id)

        try:
            report.provenance_updates = self._prov.update_provenance(paper_id, entities)
        except Exception:
            logger.exception("GraphUpdater: ProvenanceUpdater thất bại paper_id=%s", paper_id)

        try:
            report.consistency_issues = self._checker.check_consistency(
                paper_id,
                check_orphans=check_orphans,
            )
        except Exception:
            logger.exception("GraphUpdater: ConsistencyChecker thất bại paper_id=%s", paper_id)

        logger.info("GraphUpdater.run_all: done — %s", report.summary)
        return report

    def merge_entities(
        self,
        paper_id: str,
        entities: ExtractedEntities,
    ) -> MergeResult:
        """Chạy chỉ bước merge. Dùng khi cần rollback/retry riêng."""
        return self._merger.merge_entities(paper_id, entities)

    def update_provenance(
        self,
        paper_id: str,
        entities: ExtractedEntities,
    ) -> list[ProvenanceUpdate]:
        """Chạy chỉ bước provenance update."""
        return self._prov.update_provenance(paper_id, entities)

    def check_consistency(
        self,
        paper_id: str,
        check_orphans: bool = False,
    ) -> list[ConsistencyIssue]:
        """Chạy chỉ bước consistency check. Dùng cho maintenance job."""
        return self._checker.check_consistency(paper_id, check_orphans=check_orphans)


# =============================================================================
# BATCH UPDATER — chạy update cho nhiều paper
# =============================================================================

class BatchGraphUpdater:
    """
    Wrapper cho GraphUpdater để xử lý list paper.
    Dùng trong maintenance job hoặc sau khi ingest batch mới.

    Tự động:
        - Bỏ qua paper chưa có status 'kg_built' (chưa build xong)
        - Log summary tổng hợp sau khi xong
        - Không dừng batch khi 1 paper lỗi
    """

    def __init__(
        self,
        client: Neo4jClientProtocol,
        continue_on_error: bool = True,
        **updater_kwargs,
    ) -> None:
        self._updater = GraphUpdater(client, **updater_kwargs)
        self._client  = client
        self._continue_on_error = continue_on_error

    def update_batch(
        self,
        items: list[tuple[str, ExtractedEntities]],
        check_orphans: bool = False,
    ) -> list[UpdateReport]:
        """
        Chạy update cho list (paper_id, entities).

        Args:
            items:        list of (paper_id, entities)
            check_orphans: có chạy orphan check không (tốn kém, chỉ bật định kỳ)
        """
        reports: list[UpdateReport] = []
        success = failed = skipped = 0

        for paper_id, entities in items:
            existing = self._client.get_paper_by_id(paper_id)
            if not existing or existing.get("processing_status") != "kg_built":
                logger.debug(
                    "BatchGraphUpdater: skip paper_id=%s — chưa kg_built",
                    paper_id,
                )
                skipped += 1
                reports.append(UpdateReport(paper_id=paper_id))
                continue

            try:
                report = self._updater.run_all(
                    paper_id,
                    entities,
                    check_orphans=check_orphans,
                )
                reports.append(report)
                success += 1
            except Exception:
                failed += 1
                logger.exception("BatchGraphUpdater: FAILED paper_id=%s", paper_id)
                reports.append(UpdateReport(paper_id=paper_id))
                if not self._continue_on_error:
                    raise

        logger.info(
            "BatchGraphUpdater: done — success=%d failed=%d skipped=%d total=%d",
            success, failed, skipped, len(items),
        )
        return reports
