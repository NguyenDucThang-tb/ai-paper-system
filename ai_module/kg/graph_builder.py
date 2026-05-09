"""
ai_module/kg/graph_builder.py

Nhận UnifiedDocument (từ ingestion pipeline) +
ExtractedEntities (từ entity_extractor.py) +
RelationResult (từ relation_extractor.py) → build Knowledge Graph trong Neo4j.

Thứ tự giai đoạn cứng — KHÔNG thay đổi:
    Giai đoạn 1: Paper → Author + Institution → Venue → Topic → Citation stubs
    Giai đoạn 2: Method/Dataset/Task nodes + edges từ RelationResult (đã LLM verify)
    Giai đoạn 3: Chunk nodes (sau khi Qdrant đã upsert)

Mỗi giai đoạn có thể chạy độc lập nếu cần rollout dần.
Sau khi hoàn thành toàn bộ, set processing_status = 'kg_built'.

Changelog:
    v2 — 2025-05
        [fix-1] Xóa dataclass định nghĩa lại — import từ entities.py
        [fix-2] build_phase2 nhận RelationResult từ relation_extractor
                → dùng relation đã LLM verify thay vì insert thẳng từ entity
        [fix-3] doc.references guard or [] tránh TypeError khi None
        [fix-4] BASED_ON catch Exception thay vì ValueError sai type
        [fix-5] Xóa doc.doc_id = paper_id — không mutate input object
        [fix-6] _resolve_paper_id expose thành public resolve_paper_id()
        [fix-7] _merge_citation thêm _MIN_CITATION_TITLE_LEN check nhất quán
                với relation_extractor; bỏ confidence param dư thừa
        [fix-8] Document rõ rủi ro 2-source collision trong resolve_paper_id()
        [fix-9] build_phase2 dùng merge_method/dataset/task thay vì
                merge_method_node/edge không tồn tại trong neo4j_client
        [fix-10] Bỏ relations.summary() và entities.summary() — method không tồn tại
"""

from __future__ import annotations

import logging
import uuid

from storage.graph_db.neo4j_client import Neo4jClient
from ingestion.schema.document_schema import UnifiedDocument, Reference, ChunkMeta

# [fix-1] Import từ entities.py — không định nghĩa lại ở đây
from ai_module.kg.entities import (
    AuthorEntity,
    DatasetEntity,
    ExtractedEntities,
    MethodEntity,
    TaskEntity,
)

# Import RelationResult để build_phase2 dùng relation đã LLM verify  [fix-2]
from ai_module.kg.relation_extractor import (
    RelationResult,
    BasedOnRelation,
)

logger = logging.getLogger(__name__)

# Minimum title length cho citation fuzzy match — nhất quán với relation_extractor  [fix-7]
_MIN_CITATION_TITLE_LEN = 20


# =============================================================================
# GRAPH BUILDER
# =============================================================================

class GraphBuilder:
    """
    Orchestrate toàn bộ KG build flow cho 1 paper.

    Cách dùng đầy đủ (có relation_extractor):
        builder   = GraphBuilder(neo4j_client)
        entities  = entity_extractor.extract(doc)
        paper_id  = builder.resolve_paper_id(doc)
        relations = relation_extractor.extract(doc, paper_id, entities, author_id_map)
        builder.build(doc, entities, relations=relations)

    Cách dùng fallback (không có relation_extractor):
        builder.build(doc, entities)
        # build_phase2 sẽ fallback về entities trực tiếp

    Hoặc chạy từng giai đoạn riêng:
        paper_id = builder.build_phase1(doc, entities)
        builder.build_phase2(paper_id, entities, relations=relations)
        builder.build_phase3(paper_id, chunk_map)
    """

    # Namespace cố định cho uuid5 — không thay đổi giữa các lần chạy.
    # Dùng DNS namespace (RFC 4122) làm base — chỉ cần cố định, không có nghĩa đặc biệt.
    _UUID5_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Entry point chính
    # ------------------------------------------------------------------

    def build(
        self,
        doc: UnifiedDocument,
        entities: ExtractedEntities,
        relations: RelationResult | None = None,   # [fix-2] từ relation_extractor
        chunk_map: dict[str, ChunkMeta] | None = None,
    ) -> str:
        paper_id = self.resolve_paper_id(doc)  # [fix-6] public method
        logger.info("GraphBuilder.build: start paper_id=%s title='%s'", paper_id, doc.title)

        try:
            self.build_phase1(doc, entities, paper_id=paper_id)
            self.build_phase2(paper_id, entities, relations=relations)  # [fix-2]
            if chunk_map:
                self.build_phase3(paper_id, chunk_map)
            self._client.set_paper_status(paper_id, "kg_built")
        except Exception:
            logger.exception("GraphBuilder.build: FAILED paper_id=%s", paper_id)
            raise

        logger.info("GraphBuilder.build: done paper_id=%s", paper_id)
        return paper_id

    # ------------------------------------------------------------------
    # Giai đoạn 1 — Paper / Author / Venue / Topic / Citation
    # ------------------------------------------------------------------

    def build_phase1(
        self,
        doc: UnifiedDocument,
        entities: ExtractedEntities,
        paper_id: str | None = None,
    ) -> str:
        """
        Giai đoạn 1: insert Paper, Author, Institution, Venue, Topic, Citation stubs.
        Không cần LLM extraction — chỉ dùng metadata từ UnifiedDocument.

        Thứ tự cứng trong giai đoạn này:
            1. merge_paper      ← phải đầu tiên, mọi MATCH sau dùng paper_id
            2. merge_author     ← lookup fulltext trước, tránh duplicate
            3. merge_institution← sau author vì cần author_id
            4. merge_venue      ← độc lập, chỉ cần paper_id
            5. merge_topics     ← từ doc.keywords
            6. merge_citation   ← từ doc.references, tạo stub nếu chưa ingest

        Returns:
            paper_id — để caller dùng cho build_phase2/3 hoặc relation_extractor
        """
        paper_id = paper_id or self.resolve_paper_id(doc)  # [fix-6]

        # [fix-5] Không set doc.doc_id = paper_id — không mutate input object.
        # entity_extractor đã dùng getattr(doc, "doc_id", None) với fallback an toàn.
        # Nếu cần doc_id trong doc, caller tự set sau khi nhận return value.

        # 1. Paper node — phải chạy đầu tiên
        self._merge_paper(doc, paper_id)

        # 2 + 3. Author + Institution
        if not entities.authors:
            logger.warning(
                "build_phase1: paper_id=%s không có author nào — "
                "entity_extractor có thể parse thất bại hoặc paper không có author field.",
                paper_id,
            )
        for order, author in enumerate(entities.authors):
            author_id = self._merge_author(author, paper_id, order)
            if author.affiliation:
                self._merge_institution(author, author_id)

        # 4. Venue
        if doc.journal:
            self._merge_venue(doc, paper_id)

        # 5. Topics từ keywords
        if doc.keywords:
            self._client.merge_topics(
                paper_id=paper_id,
                topics=doc.keywords,
                source="keyword",
            )

        # 6. Citation stubs — [fix-3] guard or [] tránh TypeError khi None
        for ref in (doc.references or []):
            self._merge_citation(ref, paper_id)

        return paper_id

    # ------------------------------------------------------------------
    # Giai đoạn 2 — Method / Dataset / Task edges
    # ------------------------------------------------------------------

    def build_phase2(
        self,
        paper_id: str,
        entities: ExtractedEntities,
        relations: RelationResult | None = None,  # [fix-2]
    ) -> None:
        """
        Giai đoạn 2: insert Method, Dataset, Task nodes và edges.

        Strategy:
            Bước 1 — luôn insert node + edge từ entities trước
                      (dùng merge_method/dataset/task của neo4j_client)
            Bước 2 — nếu có RelationResult, gọi lại merge để update edge
                      với confidence đã LLM verify (ON MATCH SET giữ cao nhất)
            Bước 3 — BASED_ON sau khi tất cả Method node đã tồn tại

        Lý do dùng 2 lần merge thay vì tách node/edge:
            neo4j_client chỉ có merge_method/dataset/task gộp cả node lẫn edge.
            ON MATCH SET trong client đảm bảo confidence cao nhất được giữ lại
            → lần gọi thứ 2 từ RelationResult sẽ tự update nếu confidence cao hơn.
        """
        # ── Bước 1: insert node + edge từ entities (luôn chạy) ───────────
        for method in entities.methods:
            self._client.merge_method(
                paper_id=paper_id,
                method_name=method.name,
                category=method.category,
                aliases=method.aliases,
                source_section=method.source_section or "method",
                confidence=method.confidence,
                evidence=method.evidence,
            )

        for dataset in entities.datasets:
            self._client.merge_dataset(
                paper_id=paper_id,
                dataset_name=dataset.name,
                dataset_language=dataset.language,
                aliases=dataset.aliases,
                source_section=dataset.source_section or "experiment",
                confidence=dataset.confidence,
                evidence=dataset.evidence,
                metric=dataset.metric,
            )

        for task in entities.tasks:
            self._client.merge_task(
                paper_id=paper_id,
                task_name=task.name,
                source_section=task.source_section or "abstract",
                confidence=task.confidence,
                evidence=task.evidence,
            )

        # ── Bước 2: nếu có RelationResult → update edge với confidence verify ──
        # ON MATCH SET trong neo4j_client giữ confidence cao nhất tự động  [fix-9]
        if relations is not None:
            logger.debug(
                "build_phase2: override edges bằng RelationResult đã LLM verify"  # [fix-10]
            )
            self._insert_edges_from_relations(paper_id, relations)
        else:
            logger.debug(
                "build_phase2: không có RelationResult — dùng entity confidence"  # [fix-10]
            )

        # ── Bước 3: BASED_ON — sau khi tất cả Method node đã INSERT ────────
        self._merge_based_on(paper_id, entities, relations)

    def _insert_edges_from_relations(
        self,
        paper_id: str,
        relations: RelationResult,
    ) -> None:
        """
        Update edges từ RelationResult (đã LLM verify).
        Dùng merge_method/dataset/task — ON MATCH SET sẽ update confidence
        nếu RelationResult có giá trị cao hơn entity gốc.
        """
        for r in relations.uses_method:
            self._client.merge_method(
                paper_id=paper_id,
                method_name=r.method_name,
                source_section=r.source_section,
                confidence=r.confidence,
                evidence=r.evidence,
            )

        for r in relations.evaluates_on:
            self._client.merge_dataset(
                paper_id=paper_id,
                dataset_name=r.dataset_name,
                source_section=r.source_section,
                confidence=r.confidence,
                evidence=r.evidence,
                metric=r.metric,
            )

        for r in relations.addresses_task:
            self._client.merge_task(
                paper_id=paper_id,
                task_name=r.task_name,
                source_section=r.source_section,
                confidence=r.confidence,
                evidence=r.evidence,
            )

    def _merge_based_on(
        self,
        paper_id: str,
        entities: ExtractedEntities,
        relations: RelationResult | None,
    ) -> None:
        """
        Insert BASED_ON edges sau khi tất cả Method node đã tồn tại.

        Ưu tiên BasedOnRelation từ RelationResult nếu có.
        Fallback về MethodEntity.based_on nếu không có relations.

        Lưu ý về confidence:
            BASED_ON là quan hệ kế thừa kỹ thuật (phobert BASED_ON bert).
            Dùng confidence từ LLM, không hardcode 1.0 — vì đây là kết quả
            extract, không phải structural fact tuyệt đối.
        """
        based_on_list: list[BasedOnRelation] = []

        if relations is not None and relations.based_on:
            based_on_list = relations.based_on
        else:
            # Fallback: build từ entities
            for method in entities.methods:
                for parent_name in (method.based_on or []):
                    based_on_list.append(BasedOnRelation(
                        child_method=method.name,
                        parent_method=parent_name.lower().strip(),
                        confidence=method.confidence,
                    ))

        for rel in based_on_list:
            try:
                # Auto-create parent node nếu chưa tồn tại
                # paper_id=None không hợp lệ → dùng child paper_id làm placeholder
                # ON MATCH SET sẽ không overwrite nếu node đã có edge từ paper khác
                self._client.merge_method(
                    paper_id=paper_id,
                    method_name=rel.parent_method,
                    source_section="based_on",
                    confidence=0.5,   # thấp vì chỉ là placeholder, không extract trực tiếp
                    evidence=f"parent of {rel.child_method}",
                )
                self._client.merge_method_based_on(
                    child_method=rel.child_method,
                    parent_method=rel.parent_method,
                    confidence=rel.confidence,
                )
                logger.debug(
                    "_merge_based_on: OK '%s' → '%s'",
                    rel.child_method, rel.parent_method,
                )
            except Exception:
                logger.warning(
                    "_merge_based_on: BASED_ON bỏ qua — '%s' → '%s' lỗi client.",
                    rel.child_method, rel.parent_method,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Giai đoạn 3 — Chunk nodes
    # ------------------------------------------------------------------

    def build_phase3(
        self,
        paper_id: str,
        chunk_map: dict[str, ChunkMeta],
    ) -> None:
        """
        Giai đoạn 3: insert Chunk nodes sau khi Qdrant đã upsert.

        Args:
            paper_id:  UUID của paper node
            chunk_map: {qdrant_id: ChunkMeta}
        """
        for qdrant_id, meta in chunk_map.items():
            self._client.merge_chunk(
                paper_id=paper_id,
                qdrant_id=qdrant_id,
                section=meta.section,
                page=meta.page,
                chunk_text=meta.text,
            )
        logger.debug(
            "build_phase3: paper_id=%s inserted %d chunks",
            paper_id, len(chunk_map),
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def resolve_paper_id(self, doc: UnifiedDocument) -> str:  # [fix-6] public
        """
        Sinh hoặc tái tạo paper_id nhất quán từ UnifiedDocument.

        Ưu tiên:
            1. doi        → uuid5 deterministic
            2. title+year → uuid5
            3. fallback   → random UUID (không idempotent)

        ⚠️  CẢNH BÁO 2-source collision:  [fix-8]
            Nếu cùng 1 paper được ingest từ 2 nguồn — lần 1 có doi, lần 2 không —
            uuid5("doi:...") ≠ uuid5("title:...") → tạo 2 Paper node khác nhau.
            Cần pre-dedup trước khi ingest: ưu tiên source có doi,
            hoặc dùng neo4j_client.lookup_paper_by_title() trước khi MERGE.

        Lý do dùng uuid5 thay vì random UUID:
            - Idempotent: cùng doi/title luôn cho cùng paper_id
            - Pipeline crash và chạy lại sẽ MERGE đúng vào node cũ,
              không tạo duplicate.
        """
        if doc.doi and doc.doi.strip():
            raw = f"doi:{doc.doi.strip().lower()}"
        elif doc.title and doc.title.strip() and doc.title != "Unknown":
            year = doc.year or 0
            raw = f"title:{doc.title.strip().lower()}:year:{year}"
        else:
            logger.warning(
                "resolve_paper_id: không có doi lẫn title rõ ràng — dùng random UUID. "
                "Paper này sẽ không idempotent nếu pipeline chạy lại."
            )
            return str(uuid.uuid4())

        return str(uuid.uuid5(self._UUID5_NS, raw))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _merge_paper(self, doc: UnifiedDocument, paper_id: str) -> None:
        """
        Chuẩn bị params từ UnifiedDocument rồi gọi client.merge_paper().

        Lưu ý: neo4j_client.merge_paper() MERGE theo doi (nếu có)
        hoặc (title, year) — KHÔNG MERGE theo id.
        Xem neo4j_schema.cypher Section 6 — MERGE templates.
        """
        self._client.merge_paper({
            "id":             paper_id,
            "title":          doc.title,
            "year":           doc.year,
            "doi":            doc.doi,
            "abstract":       doc.abstract,
            "language":       getattr(doc, "language", None) or "vi",
            "source_file":    getattr(doc, "source_file", None),
            "source_type":    getattr(doc, "source_type", None),
            "page_count":     getattr(doc, "page_count", None),
            "citation_count": getattr(doc, "citation_count", None),
            "chunk_ids":      getattr(doc, "chunk_ids", None) or [],
        })
        logger.debug("_merge_paper: paper_id=%s doi=%s", paper_id, doc.doi)

    def _merge_author(
        self,
        author: AuthorEntity,
        paper_id: str,
        order: int,
    ) -> str:
        """
        Lookup author trước để tránh duplicate, rồi MERGE.
        Trả về author_id để caller dùng cho merge_institution.
        """
        existing_id = self._client.lookup_author_by_fulltext(
            name=author.name,
            affiliation=author.affiliation,
            threshold=0.8,
        )
        author_raw = (
            f"author:{author.name.strip().lower()}"
            f":{(author.affiliation or '').strip().lower()}"
        )
        author_id = existing_id or str(uuid.uuid5(self._UUID5_NS, author_raw))

        self._client.merge_author(
            author_id=author_id,
            name=author.name,
            paper_id=paper_id,
            order=order,
            email=author.email,
            affiliation=author.affiliation,
        )
        logger.debug(
            "_merge_author: '%s' order=%d %s",
            author.name, order,
            "matched existing" if existing_id else "created new",
        )
        return author_id

    def _merge_institution(
        self,
        author: AuthorEntity,
        author_id: str,
    ) -> None:
        """
        Gọi client.merge_institution().
        Chỉ gọi khi author.affiliation không rỗng — check ở caller.
        """
        self._client.merge_institution(
            author_id=author_id,
            display_name=author.affiliation,  # type: ignore[arg-type]
            country=author.country,
            inst_type=author.institution_type,
        )

    def _merge_venue(self, doc: UnifiedDocument, paper_id: str) -> None:
        """Gọi client.merge_venue() từ metadata của UnifiedDocument."""
        self._client.merge_venue(
            paper_id=paper_id,
            venue_name=doc.journal,  # type: ignore[arg-type]
            venue_type=self._infer_venue_type(doc.journal or ""),
            publisher=getattr(doc, "publisher", None),
            volume=getattr(doc, "volume", None),
            issue=getattr(doc, "issue", None),
            pages=getattr(doc, "pages", None),
        )

    def _merge_citation(self, ref: Reference, citing_paper_id: str) -> None:
        """
        Gọi client.merge_citation() từ Reference object.

        [fix-7]:
        - ref.doi        → confidence 1.0, luôn insert
        - ref.title+year → confidence 0.8, insert nếu title đủ dài
        - ref.title only → confidence 0.6, insert nếu title đủ dài
        - không có doi lẫn title → bỏ qua
        - confidence KHÔNG truyền vào client — client tự tính từ doi/year
        """
        if not ref.doi and not ref.title:
            logger.debug(
                "_merge_citation: bỏ qua — không có doi lẫn title | '%s'",
                getattr(ref, "raw_text", "")[:80],
            )
            return

        # [fix-7] Bỏ qua title quá ngắn/generic để tránh collision
        if not ref.doi and ref.title and len(ref.title.strip()) < _MIN_CITATION_TITLE_LEN:
            logger.debug(
                "_merge_citation: bỏ qua title quá ngắn '%s' (< %d chars)",
                ref.title, _MIN_CITATION_TITLE_LEN,
            )
            return

        self._client.merge_citation(
            citing_paper_id=citing_paper_id,
            cited_doi=getattr(ref, "doi", None),
            cited_title=getattr(ref, "title", None),
            cited_year=getattr(ref, "year", None),
            raw_ref_text=getattr(ref, "raw_text", ""),
            # [fix-7] KHÔNG truyền confidence — neo4j_client tự tính từ doi/year
        )

    @staticmethod
    def _infer_venue_type(venue_name: str) -> str:
        name_lower = venue_name.lower()
        if any(kw in name_lower for kw in (
            "conference", "proceedings", "workshop",
            "acl", "emnlp", "naacl", "coling",
        )):
            return "conference"
        if any(kw in name_lower for kw in ("arxiv", "preprint")):
            return "preprint"
        return "journal"


# =============================================================================
# BATCH BUILDER — xử lý nhiều paper
# =============================================================================

class BatchGraphBuilder:
    """
    Wrapper cho GraphBuilder để xử lý list paper.
    Dùng trong scripts/build_kg.py hoặc celery_worker.py.

    Tự động:
        - Bỏ qua paper đã có status 'kg_built' (idempotent)
        - Log summary sau khi xong
        - Không dừng batch khi 1 paper lỗi (continue_on_error=True)
    """

    def __init__(
        self,
        client: Neo4jClient,
        continue_on_error: bool = True,
    ) -> None:
        self._builder = GraphBuilder(client)
        self._client = client
        self._continue_on_error = continue_on_error

    def build_batch(
        self,
        items: list[tuple[UnifiedDocument, ExtractedEntities]],
        relations_map: dict[str, RelationResult] | None = None,  # [fix-2]
        chunk_maps: dict[str, dict[str, ChunkMeta]] | None = None,
    ) -> dict[str, str]:
        """
        Build KG cho list (UnifiedDocument, ExtractedEntities).

        Args:
            items:         list of (doc, entities) pairs
            relations_map: {paper_id: RelationResult} — optional,
                           từ relation_extractor, nếu có sẽ dùng relation đã verify
            chunk_maps:    {paper_id: {qdrant_id: ChunkMeta}} — optional

        Returns:
            {paper_id: paper_title}
        """
        results: dict[str, str] = {}
        success = failed = skipped = 0

        for doc, entities in items:
            paper_id = self._builder.resolve_paper_id(doc)  # [fix-6] public method

            # Skip nếu đã build
            existing = self._client.get_paper_by_id(paper_id)
            if existing and existing.get("processing_status") == "kg_built":
                logger.debug("build_batch: skip '%s' — already kg_built", doc.title)
                skipped += 1
                results[paper_id] = doc.title
                continue

            try:
                relations  = (relations_map or {}).get(paper_id)   # [fix-2]
                chunk_map  = (chunk_maps or {}).get(paper_id)
                self._builder.build(
                    doc, entities,
                    relations=relations,
                    chunk_map=chunk_map,
                )
                results[paper_id] = doc.title
                success += 1
            except Exception:
                failed += 1
                logger.exception("build_batch: FAILED '%s'", doc.title)
                if not self._continue_on_error:
                    raise

        logger.info(
            "build_batch: done — success=%d failed=%d skipped=%d total=%d",
            success, failed, skipped, len(items),
        )
        return results
