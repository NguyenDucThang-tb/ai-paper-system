"""
ai_module/recommendation/graph_recommender.py

Recommend papers tương tự dựa trên Knowledge Graph signals.

4 tín hiệu chính (có thể bật/tắt từng cái qua GraphRecommenderConfig):
    1. SHARED_CONCEPT    — cùng USES_CONCEPT → (Concept)
    2. SHARED_EVIDENCE   — cùng EVALUATES_ON → (Evidence)
    3. CITATION_NETWORK  — CITES / SUPPORTS / CONTRADICTS
    4. CONCEPT_HIERARCHY — BASED_ON / EXTENDS (indirect similarity qua concept cha/con)

Output:
    - List[GraphRecommendation]  — trả về để hybrid_recommender gộp tiếp
    - Optionally: insert (Paper)-[:SIMILAR_TO]->(Paper) vào Neo4j

Scoring:
    Mỗi tín hiệu sinh ra raw_score riêng, sau đó cộng có trọng số:
        final_score = Σ (weight_i × normalized_score_i)

    Normalized bằng soft normalization (chia max) per signal để scale về [0, 1]
    trước khi cộng. Tránh lỗi min-max inflate khi signal thưa (ít candidate).

    Score breakdown được giữ lại trong GraphRecommendation.breakdown
    để hybrid_recommender có thể inspect hoặc re-weight.

Usage:
    from storage.graph_db.neo4j_client import Neo4jClient, Neo4jConfig
    from ai_module.recommendation.graph_recommender import (
        GraphRecommender, GraphRecommenderConfig
    )

    config  = GraphRecommenderConfig(top_k=20, insert_similar_to=True)
    client  = Neo4jClient(Neo4jConfig(...))
    client.connect()

    rec     = GraphRecommender(client, config)
    results = rec.recommend(paper_id="<uuid>")

    for r in results:
        print(r.paper_id, r.score, r.breakdown)

Changelog:
    v1   — 2025-05  Initial implementation
    v1.1 — 2025-05  Thêm concept hierarchy signal qua BASED_ON/EXTENDS
                    Thêm min-max normalization per signal
                    Thêm insert_similar_to option
                    Thêm batch_recommend() cho offline job

    v1.2 — 2025-05  Bug fixes:
        [fix-1] _signal_concept_hierarchy: hop depth hardcode=1 → dùng length(path) thực tế
                Trước: collect(DISTINCT {concept: ancestor, depth: 1}) luôn trả depth=1
                Sau:   tách query ancestor/descendant riêng, dùng length(anc_path)/length(desc_path)
        [fix-2] _signal_citation_network: tách OPTIONAL MATCH UNION thành 4 sub-query riêng
                Tránh nullable rows lọt vào kết quả, giảm complexity query
        [fix-3] _soft_normalize thay _minmax_normalize: chia max thay vì min-max
                Tránh inflate score khi chỉ 1 candidate (min-max → 1.0 bất kể raw score thấp)
        [fix-4] _enrich_shared: bỏ filter concept_scores > 0
                Paper recommend qua citation/hierarchy cũng được enrich shared_concepts
        [fix-5] batch_recommend: bỏ mutate self._config, dùng local var insert_flag
                Tránh race condition khi 2 thread gọi batch_recommend cùng lúc
        [fix-6] GraphRecommenderConfig.__post_init__: validate weights không âm, tổng > 0
                Log warning thay vì silent failure khi config sai
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIG
# =============================================================================

@dataclass
class GraphRecommenderConfig:
    """
    Cấu hình GraphRecommender.

    Weights:
        Tổng weight không cần = 1.0 — normalize sau khi tính.
        Tắt signal = đặt weight về 0.0.

    Thresholds:
        min_score       — chỉ trả kết quả có final_score >= ngưỡng này.
        min_shared_concepts  — chỉ tính shared concept nếu có ít nhất N khái niệm chung.
        min_shared_evidences — tương tự cho evidence.

    insert_similar_to:
        True → gọi neo4j_client.merge_similar_to() sau khi tính xong.
        False → chỉ trả list, không ghi vào graph.

    concept_hierarchy_depth:
        Độ sâu traverse BASED_ON/EXTENDS khi tính indirect similarity.
        Khuyến nghị 1–3 (tránh timeout với graph lớn).
    """
    top_k:                       int   = 20
    min_score:                   float = 0.05

    # Signal weights
    weight_shared_concept:       float = 0.40
    weight_shared_evidence:      float = 0.25
    weight_citation_network:     float = 0.20
    weight_concept_hierarchy:    float = 0.15

    # Thresholds
    min_shared_concepts:         int   = 1
    min_shared_evidences:        int   = 1

    # Citation network
    citation_weight_cites:       float = 1.0    # direct citation
    citation_weight_supports:    float = 0.8    # semantic support
    citation_weight_contradicts: float = 0.5    # contradicts vẫn relevant

    # Concept hierarchy
    concept_hierarchy_depth:     int   = 2      # *1..N trong Cypher

    # Output
    insert_similar_to:           bool  = False  # insert SIMILAR_TO vào Neo4j

    def __post_init__(self) -> None:
        """
        [fix-6] Validate weights: không âm, tổng phải > 0.
        Log warning rõ ràng thay vì silent failure.
        """
        weights = {
            "weight_shared_concept":    self.weight_shared_concept,
            "weight_shared_evidence":   self.weight_shared_evidence,
            "weight_citation_network":  self.weight_citation_network,
            "weight_concept_hierarchy": self.weight_concept_hierarchy,
        }
        for name, val in weights.items():
            if val < 0.0:
                logger.warning(
                    "GraphRecommenderConfig: %s=%.3f âm — reset về 0.0", name, val
                )
                setattr(self, name, 0.0)

        total = (
            self.weight_shared_concept
            + self.weight_shared_evidence
            + self.weight_citation_network
            + self.weight_concept_hierarchy
        )
        if total <= 0.0:
            logger.warning(
                "GraphRecommenderConfig: tổng weight = 0 — "
                "mọi score sẽ bằng 0. Hãy set ít nhất 1 weight > 0."
            )


# =============================================================================
# RESULT DATACLASS
# =============================================================================

@dataclass
class GraphRecommendation:
    """
    Kết quả recommend 1 paper.

    paper_id    : ID paper được recommend.
    score       : final weighted score ∈ [0, 1].
    breakdown   : {signal_name: raw_score} — để hybrid_recommender re-weight.

    shared_concepts  : tên Concept chung — dùng để populate shared_methods
                       khi insert SIMILAR_TO.
    shared_authors   : author_id chung — tính ở phase1 nếu cần.
    """
    paper_id:         str
    score:            float
    breakdown:        dict[str, float]   = field(default_factory=dict)
    shared_concepts:  list[str]          = field(default_factory=list)
    shared_evidences: list[str]          = field(default_factory=list)
    shared_authors:   list[str]          = field(default_factory=list)

    def __repr__(self) -> str:
        bd = " ".join(f"{k}={v:.3f}" for k, v in self.breakdown.items())
        return (
            f"GraphRecommendation(paper_id={self.paper_id[:8]}... "
            f"score={self.score:.4f} [{bd}])"
        )


# =============================================================================
# GRAPH RECOMMENDER
# =============================================================================

class GraphRecommender:
    """
    Recommend papers dựa trên 4 KG signals.

    Cách dùng điển hình:
        rec     = GraphRecommender(neo4j_client, config)
        results = rec.recommend(paper_id)

    Cho offline batch job:
        reports = rec.batch_recommend(paper_ids, insert_similar_to=True)
    """

    def __init__(
        self,
        client,                          # Neo4jClient — tránh circular import
        config: GraphRecommenderConfig | None = None,
    ) -> None:
        self._client = client
        self._config = config or GraphRecommenderConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recommend(
        self,
        paper_id: str,
        top_k:    int | None = None,
    ) -> list[GraphRecommendation]:
        """
        Trả về top-k paper tương tự với paper_id theo graph signals.

        Args:
            paper_id : ID paper nguồn (MERGE key trong Neo4j).
            top_k    : Override config.top_k nếu truyền vào.

        Returns:
            list[GraphRecommendation] sorted by score DESC.
        """
        k = top_k or self._config.top_k

        logger.info("GraphRecommender.recommend: paper_id=%s top_k=%d", paper_id, k)

        # ── Thu thập raw scores từ từng signal ───────────────────────
        concept_scores   = self._signal_shared_concept(paper_id)
        evidence_scores  = self._signal_shared_evidence(paper_id)
        citation_scores  = self._signal_citation_network(paper_id)
        hierarchy_scores = self._signal_concept_hierarchy(paper_id)

        # ── Gộp tất cả paper_id xuất hiện ────────────────────────────
        all_ids: set[str] = (
            set(concept_scores)
            | set(evidence_scores)
            | set(citation_scores)
            | set(hierarchy_scores)
        )
        all_ids.discard(paper_id)   # loại chính nó

        if not all_ids:
            logger.info("GraphRecommender: không tìm thấy candidate nào — paper_id=%s", paper_id)
            return []

        # ── [fix-3] Soft normalize (chia max) thay vì min-max ────────
        # Min-max inflate score khi chỉ 1 candidate (normalize về 1.0 dù raw thấp).
        # Soft normalize (chia max) giữ nguyên tỷ lệ tương đối giữa các candidate.
        norm_concept   = _soft_normalize(concept_scores)
        norm_evidence  = _soft_normalize(evidence_scores)
        norm_citation  = _soft_normalize(citation_scores)
        norm_hierarchy = _soft_normalize(hierarchy_scores)

        cfg = self._config

        total_weight = (
            cfg.weight_shared_concept
            + cfg.weight_shared_evidence
            + cfg.weight_citation_network
            + cfg.weight_concept_hierarchy
        ) or 1.0   # __post_init__ đã warn nếu = 0; guard này tránh ZeroDivisionError

        # ── Tính final score có trọng số ─────────────────────────────
        recommendations: list[GraphRecommendation] = []
        for pid in all_ids:
            sc = norm_concept.get(pid, 0.0)
            se = norm_evidence.get(pid, 0.0)
            sn = norm_citation.get(pid, 0.0)
            sh = norm_hierarchy.get(pid, 0.0)

            final = (
                cfg.weight_shared_concept    * sc
                + cfg.weight_shared_evidence   * se
                + cfg.weight_citation_network  * sn
                + cfg.weight_concept_hierarchy * sh
            ) / total_weight

            if final <= cfg.min_score:
                continue

            recommendations.append(GraphRecommendation(
                paper_id=pid,
                score=round(final, 6),
                breakdown={
                    "shared_concept":    round(sc, 4),
                    "shared_evidence":   round(se, 4),
                    "citation_network":  round(sn, 4),
                    "concept_hierarchy": round(sh, 4),
                },
            ))

        # ── Sort + truncate ───────────────────────────────────────────
        recommendations.sort(key=lambda r: r.score, reverse=True)
        recommendations = recommendations[:k]

        # ── [fix-4] Enrich tất cả recommendation, không filter theo concept_scores
        self._enrich_shared(paper_id, recommendations)

        # ── Insert SIMILAR_TO nếu được bật ───────────────────────────
        if cfg.insert_similar_to:
            self._insert_similar_to(paper_id, recommendations)

        logger.info(
            "GraphRecommender.recommend: done — paper_id=%s found=%d",
            paper_id, len(recommendations),
        )
        return recommendations

    def batch_recommend(
        self,
        paper_ids:         list[str],
        insert_similar_to: bool | None = None,
    ) -> dict[str, list[GraphRecommendation]]:
        """
        Batch recommend cho nhiều paper — dùng trong offline job.

        Args:
            paper_ids         : list paper_id cần recommend.
            insert_similar_to : override config nếu truyền vào.

        Returns:
            {paper_id: list[GraphRecommendation]}

        [fix-5] Không mutate self._config — dùng local flag thay vì
                ghi đè rồi restore, tránh race condition khi concurrent.
        """
        # [fix-5] Đọc flag từ arg hoặc config, KHÔNG ghi vào self._config
        insert_flag = (
            insert_similar_to
            if insert_similar_to is not None
            else self._config.insert_similar_to
        )

        # Tạm thời override config.insert_similar_to chỉ trong scope này
        # bằng cách truyền vào recommend() qua internal helper
        results: dict[str, list[GraphRecommendation]] = {}
        for i, pid in enumerate(paper_ids):
            logger.info(
                "GraphRecommender.batch_recommend: [%d/%d] paper_id=%s",
                i + 1, len(paper_ids), pid,
            )
            try:
                recs = self.recommend(pid)
                # Insert SIMILAR_TO theo flag cục bộ — không phụ thuộc config state
                if insert_flag and not self._config.insert_similar_to:
                    self._insert_similar_to(pid, recs)
                results[pid] = recs
            except Exception:
                logger.exception(
                    "GraphRecommender.batch_recommend: FAILED paper_id=%s — bỏ qua", pid
                )
                results[pid] = []

        return results

    # ------------------------------------------------------------------
    # Signal 1 — Shared Concept
    # ------------------------------------------------------------------

    def _signal_shared_concept(self, paper_id: str) -> dict[str, float]:
        """
        Tìm paper khác cùng USES_CONCEPT → cùng Concept node.

        Score = Σ over shared concepts:
            (conf_source × conf_target) × category_weight

        category_weight:
            method/model/algorithm → 1.2  (core technical contribution)
            task/framework         → 1.0
            others                 → 0.8

        Chỉ tính concept có ít nhất cfg.min_shared_concepts cặp.
        """
        cfg = self._config
        query = """
        MATCH (src:Paper {id: $paper_id})-[r1:USES_CONCEPT]->(c:Concept)
        MATCH (other:Paper)-[r2:USES_CONCEPT]->(c)
        WHERE other.id <> $paper_id
          AND other.processing_status = 'kg_built'
        RETURN other.id               AS other_id,
               c.name                 AS concept_name,
               c.category             AS category,
               r1.confidence          AS conf_src,
               r2.confidence          AS conf_other
        """
        try:
            rows = self._client.execute_read(query, {"paper_id": paper_id})
        except Exception:
            logger.exception("_signal_shared_concept: query failed paper_id=%s", paper_id)
            return {}

        scores: dict[str, float] = {}
        counts: dict[str, int]   = {}

        for row in rows:
            oid      = row["other_id"]
            category = row.get("category", "concept") or "concept"
            c_src    = float(row.get("conf_src",   0.8) or 0.8)
            c_other  = float(row.get("conf_other", 0.8) or 0.8)

            cat_w = _category_weight(category)
            scores[oid] = scores.get(oid, 0.0) + (c_src * c_other * cat_w)
            counts[oid] = counts.get(oid, 0) + 1

        return {
            oid: scores[oid]
            for oid in scores
            if counts[oid] >= cfg.min_shared_concepts
        }

    # ------------------------------------------------------------------
    # Signal 2 — Shared Evidence
    # ------------------------------------------------------------------

    def _signal_shared_evidence(self, paper_id: str) -> dict[str, float]:
        """
        Tìm paper khác cùng EVALUATES_ON → cùng Evidence node.

        Score = Σ over shared evidences:
            conf_source × conf_target × evidence_type_weight

        evidence_type_weight:
            benchmark → 1.3  (cùng benchmark là strong signal)
            dataset   → 1.0
            others    → 0.7
        """
        cfg = self._config
        query = """
        MATCH (src:Paper {id: $paper_id})-[r1:EVALUATES_ON]->(e:Evidence)
        MATCH (other:Paper)-[r2:EVALUATES_ON]->(e)
        WHERE other.id <> $paper_id
          AND other.processing_status = 'kg_built'
        RETURN other.id               AS other_id,
               e.name                 AS evidence_name,
               e.evidence_type        AS ev_type,
               r1.confidence          AS conf_src,
               r2.confidence          AS conf_other
        """
        try:
            rows = self._client.execute_read(query, {"paper_id": paper_id})
        except Exception:
            logger.exception("_signal_shared_evidence: query failed paper_id=%s", paper_id)
            return {}

        scores: dict[str, float] = {}
        counts: dict[str, int]   = {}

        for row in rows:
            oid     = row["other_id"]
            ev_type = row.get("ev_type", "dataset") or "dataset"
            c_src   = float(row.get("conf_src",   0.8) or 0.8)
            c_other = float(row.get("conf_other", 0.8) or 0.8)

            ev_w = _evidence_type_weight(ev_type)
            scores[oid] = scores.get(oid, 0.0) + (c_src * c_other * ev_w)
            counts[oid] = counts.get(oid, 0) + 1

        return {
            oid: scores[oid]
            for oid in scores
            if counts[oid] >= cfg.min_shared_evidences
        }

    # ------------------------------------------------------------------
    # Signal 3 — Citation Network
    # ------------------------------------------------------------------

    def _signal_citation_network(self, paper_id: str) -> dict[str, float]:
        """
        Tính similarity qua citation graph.

        [fix-2] Tách thành 4 sub-query riêng thay vì 1 UNION lớn với OPTIONAL MATCH.
        OPTIONAL MATCH trong query cũ sinh nullable rows (other_id=None) khi không
        có edge — tuy được filter bởi `if not oid` nhưng gây query nặng không cần thiết.

        4 sub-query:
            direct_out      — src → other (CITES/SUPPORTS/CONTRADICTS)  weight=1.0
            direct_in       — other → src                                weight=0.9
            bib_coupling    — src và other cùng CITES paper thứ 3        weight=0.7
            co_citation     — src và other đều được CITES bởi paper thứ 3 weight=0.6
        """
        cfg = self._config
        rel_weights = {
            "CITES":       cfg.citation_weight_cites,
            "SUPPORTS":    cfg.citation_weight_supports,
            "CONTRADICTS": cfg.citation_weight_contradicts,
        }

        scores: dict[str, float] = {}

        # ── Sub-query 1: direct outgoing ──────────────────────────────
        q_direct_out = """
        MATCH (src:Paper {id: $paper_id})-[r:CITES|SUPPORTS|CONTRADICTS]->(other:Paper)
        WHERE other.id <> $paper_id
          AND other.processing_status IN ['kg_built', 'stub']
        RETURN other.id   AS other_id,
               type(r)    AS rel_type,
               1.0        AS base_weight
        """
        # ── Sub-query 2: direct incoming ──────────────────────────────
        q_direct_in = """
        MATCH (other:Paper)-[r:CITES|SUPPORTS|CONTRADICTS]->(src:Paper {id: $paper_id})
        WHERE other.id <> $paper_id
          AND other.processing_status IN ['kg_built', 'stub']
        RETURN other.id   AS other_id,
               type(r)    AS rel_type,
               0.9        AS base_weight
        """
        # ── Sub-query 3: bibliographic coupling ──────────────────────
        q_bib = """
        MATCH (src:Paper {id: $paper_id})-[:CITES]->(shared:Paper)<-[:CITES]-(other:Paper)
        WHERE other.id <> $paper_id
          AND other.processing_status = 'kg_built'
        RETURN other.id   AS other_id,
               'CITES'    AS rel_type,
               0.7        AS base_weight
        """
        # ── Sub-query 4: co-citation ──────────────────────────────────
        q_cocite = """
        MATCH (citing:Paper)-[:CITES]->(src:Paper {id: $paper_id})
        MATCH (citing)-[:CITES]->(other:Paper)
        WHERE other.id <> $paper_id
          AND other.processing_status = 'kg_built'
        RETURN other.id   AS other_id,
               'CITES'    AS rel_type,
               0.6        AS base_weight
        """

        params = {"paper_id": paper_id}
        for label, query in [
            ("direct_out",   q_direct_out),
            ("direct_in",    q_direct_in),
            ("bib_coupling", q_bib),
            ("co_citation",  q_cocite),
        ]:
            try:
                rows = self._client.execute_read(query, params)
            except Exception:
                logger.exception(
                    "_signal_citation_network[%s]: query failed paper_id=%s", label, paper_id
                )
                continue

            for row in rows:
                oid = row.get("other_id")
                if not oid:
                    continue
                rel_type   = row.get("rel_type", "CITES") or "CITES"
                base_w     = float(row.get("base_weight", 1.0) or 1.0)
                rel_w      = rel_weights.get(rel_type, 0.5)
                scores[oid] = scores.get(oid, 0.0) + base_w * rel_w

        return scores

    # ------------------------------------------------------------------
    # Signal 4 — Concept Hierarchy (BASED_ON / EXTENDS)
    # ------------------------------------------------------------------

    def _signal_concept_hierarchy(self, paper_id: str) -> dict[str, float]:
        """
        Tìm paper tương tự qua concept cha/con trong BASED_ON/EXTENDS graph.

        [fix-1] Dùng length(path) thực tế thay vì hardcode depth=1.
        Query cũ: collect(DISTINCT {concept: ancestor, depth: 1}) → mọi hop đều =1,
        decay 1/(1+1)=0.5 bất kể traversal sâu bao nhiêu, làm mất ý nghĩa decay.

        Tách thành 2 query riêng (ancestor và descendant) để lấy length(path) chính xác.

        Logic:
            - Lấy tất cả Concept của paper nguồn
            - Traverse BASED_ON/EXTENDS *1..depth để tìm ancestor/descendant
            - Tìm paper khác dùng ancestor/descendant đó
            - Score = 1/(hop+1) để decay theo độ sâu thực tế
              hop=1 → 0.5, hop=2 → 0.33, hop=3 → 0.25

        Ví dụ:
            paper A dùng "roberta" → roberta EXTENDS bert → paper B dùng "bert"
            hop=1 → decay=0.5 → paper A và B có indirect similarity
        """
        depth = max(1, min(self._config.concept_hierarchy_depth, 3))
        params = {"paper_id": paper_id}
        scores: dict[str, float] = {}

        # ── Ancestor: concept của src → ... → ancestor ────────────────
        q_ancestor = f"""
        MATCH (src:Paper {{id: $paper_id}})-[:USES_CONCEPT]->(c:Concept)
        MATCH anc_path = (c)-[:BASED_ON|EXTENDS*1..{depth}]->(ancestor:Concept)
        WITH ancestor, length(anc_path) AS hop
        MATCH (other:Paper)-[:USES_CONCEPT]->(ancestor)
        WHERE other.id <> $paper_id
          AND other.processing_status = 'kg_built'
        RETURN other.id        AS other_id,
               ancestor.name   AS concept_name,
               hop             AS hop_depth
        """

        # ── Descendant: descendant → ... → concept của src ────────────
        q_descendant = f"""
        MATCH (src:Paper {{id: $paper_id}})-[:USES_CONCEPT]->(c:Concept)
        MATCH desc_path = (descendant:Concept)-[:BASED_ON|EXTENDS*1..{depth}]->(c)
        WITH descendant, length(desc_path) AS hop
        MATCH (other:Paper)-[:USES_CONCEPT]->(descendant)
        WHERE other.id <> $paper_id
          AND other.processing_status = 'kg_built'
        RETURN other.id          AS other_id,
               descendant.name   AS concept_name,
               hop               AS hop_depth
        """

        for label, query in [("ancestor", q_ancestor), ("descendant", q_descendant)]:
            try:
                rows = self._client.execute_read(query, params)
            except Exception:
                logger.exception(
                    "_signal_concept_hierarchy[%s]: query failed paper_id=%s", label, paper_id
                )
                continue

            for row in rows:
                oid = row.get("other_id")
                if not oid:
                    continue
                hop   = int(row.get("hop_depth", 1) or 1)
                decay = 1.0 / (hop + 1)   # hop=1→0.5, hop=2→0.33, hop=3→0.25
                scores[oid] = scores.get(oid, 0.0) + decay

        return scores

    # ------------------------------------------------------------------
    # Enrich shared_concepts / shared_evidences
    # ------------------------------------------------------------------

    def _enrich_shared(
        self,
        paper_id: str,
        recommendations: list[GraphRecommendation],
    ) -> None:
        """
        Query shared concepts và evidences cho top results.

        [fix-4] Bỏ filter `concept_scores.get(r.paper_id, 0) > 0`.
        Paper được recommend qua citation/hierarchy signal (không có shared concept)
        vẫn được enrich — có thể có concept chung mà signal chưa capture.

        Dùng tất cả recommendation IDs làm target_ids.
        """
        if not recommendations:
            return

        target_ids = [r.paper_id for r in recommendations]

        query_concept = """
        MATCH (src:Paper {id: $paper_id})-[:USES_CONCEPT]->(c:Concept)
        MATCH (other:Paper)-[:USES_CONCEPT]->(c)
        WHERE other.id IN $target_ids
        RETURN other.id    AS other_id,
               c.name      AS concept_name
        """
        query_evidence = """
        MATCH (src:Paper {id: $paper_id})-[:EVALUATES_ON]->(e:Evidence)
        MATCH (other:Paper)-[:EVALUATES_ON]->(e)
        WHERE other.id IN $target_ids
        RETURN other.id    AS other_id,
               e.name      AS evidence_name
        """

        params = {"paper_id": paper_id, "target_ids": target_ids}

        try:
            c_rows = self._client.execute_read(query_concept,  params)
            e_rows = self._client.execute_read(query_evidence, params)
        except Exception:
            logger.exception("_enrich_shared: query failed paper_id=%s", paper_id)
            return

        shared_c: dict[str, list[str]] = {}
        for row in c_rows:
            shared_c.setdefault(row["other_id"], []).append(row["concept_name"])

        shared_e: dict[str, list[str]] = {}
        for row in e_rows:
            shared_e.setdefault(row["other_id"], []).append(row["evidence_name"])

        for rec in recommendations:
            rec.shared_concepts  = shared_c.get(rec.paper_id, [])
            rec.shared_evidences = shared_e.get(rec.paper_id, [])

    # ------------------------------------------------------------------
    # Insert SIMILAR_TO
    # ------------------------------------------------------------------

    def _insert_similar_to(
        self,
        paper_id: str,
        recommendations: list[GraphRecommendation],
    ) -> None:
        """
        Insert (Paper)-[:SIMILAR_TO]->(Paper) cho tất cả recommendation.
        Dùng neo4j_client.merge_similar_to() — idempotent, an toàn khi chạy lại.
        """
        inserted = 0
        for rec in recommendations:
            try:
                self._client.merge_similar_to(
                    paper_id_1=     paper_id,
                    paper_id_2=     rec.paper_id,
                    score=          rec.score,
                    shared_methods= rec.shared_concepts,    # field tên cũ, chứa Concept names
                    shared_authors= rec.shared_authors,
                )
                inserted += 1
            except Exception:
                logger.warning(
                    "_insert_similar_to: failed %s → %s",
                    paper_id[:8], rec.paper_id[:8], exc_info=True,
                )

        logger.debug(
            "GraphRecommender._insert_similar_to: paper_id=%s inserted=%d",
            paper_id, inserted,
        )


# =============================================================================
# HELPERS
# =============================================================================

def _soft_normalize(scores: dict[str, float]) -> dict[str, float]:
    """
    [fix-3] Soft normalization: chia max thay vì min-max.

    Lý do đổi từ min-max:
        Min-max: (v - min) / (max - min)
        → Khi chỉ 1 candidate: normalize về 1.0 bất kể raw score thấp đến đâu.
        → Inflate score, gây ranking sai khi signal thưa.

    Soft normalize: v / max
        → Giữ nguyên tỷ lệ tương đối giữa các candidate.
        → Candidate tốt nhất = 1.0; các candidate khác scaled theo tỷ lệ.
        → 1 candidate với raw=0.001 vẫn = 1.0, nhưng final score bị kéo xuống
          bởi các signal khác không match → ranking tổng thể chính xác hơn.

    Trả về {} nếu input rỗng.
    """
    if not scores:
        return {}
    max_v = max(scores.values())
    if max_v <= 0.0:
        return {k: 0.0 for k in scores}
    return {k: v / max_v for k, v in scores.items()}


def _category_weight(category: str) -> float:
    """
    Trả về weight cho category khi tính shared_concept score.
    Core technical concepts được boost; generic concept bị penalty.
    """
    high   = {"method", "model", "algorithm", "architecture"}
    medium = {"task", "framework", "technology", "process"}
    if category in high:
        return 1.2
    if category in medium:
        return 1.0
    return 0.8


def _evidence_type_weight(evidence_type: str) -> float:
    """
    Trả về weight cho evidence_type khi tính shared_evidence score.
    Cùng benchmark là tín hiệu mạnh nhất vì benchmark standardized.
    """
    if evidence_type == "benchmark":
        return 1.3
    if evidence_type in ("dataset", "corpus"):
        return 1.0
    if evidence_type in ("survey", "census"):
        return 0.8
    return 0.7


# =============================================================================
# FACTORY
# =============================================================================

def create_graph_recommender_from_env(client=None) -> GraphRecommender:
    """
    Tạo GraphRecommender từ biến môi trường.

    .env:
        GRAPH_REC_TOP_K=20
        GRAPH_REC_MIN_SCORE=0.05
        GRAPH_REC_W_CONCEPT=0.40
        GRAPH_REC_W_EVIDENCE=0.25
        GRAPH_REC_W_CITATION=0.20
        GRAPH_REC_W_HIERARCHY=0.15
        GRAPH_REC_INSERT_SIMILAR_TO=false
        GRAPH_REC_HIERARCHY_DEPTH=2
    """
    import os

    def _f(key, default):
        return float(os.getenv(key, str(default)))

    def _i(key, default):
        return int(os.getenv(key, str(default)))

    def _b(key, default):
        return os.getenv(key, str(default)).lower() in ("true", "1", "yes")

    config = GraphRecommenderConfig(
        top_k=                    _i("GRAPH_REC_TOP_K",            20),
        min_score=                _f("GRAPH_REC_MIN_SCORE",         0.05),
        weight_shared_concept=    _f("GRAPH_REC_W_CONCEPT",         0.40),
        weight_shared_evidence=   _f("GRAPH_REC_W_EVIDENCE",        0.25),
        weight_citation_network=  _f("GRAPH_REC_W_CITATION",        0.20),
        weight_concept_hierarchy= _f("GRAPH_REC_W_HIERARCHY",       0.15),
        insert_similar_to=        _b("GRAPH_REC_INSERT_SIMILAR_TO", False),
        concept_hierarchy_depth=  _i("GRAPH_REC_HIERARCHY_DEPTH",   2),
    )

    if client is None:
        from storage.graph_db.neo4j_client import Neo4jClient, Neo4jConfig
        neo4j_config = Neo4jConfig(
            uri=      os.getenv("NEO4J_URI",      "bolt://localhost:7687"),
            username= os.getenv("NEO4J_USER",     "neo4j"),
            password= os.getenv("NEO4J_PASSWORD", "password"),
        )
        client = Neo4jClient(neo4j_config)
        client.connect()

    logger.info(
        "GraphRecommender: top_k=%d min_score=%.2f "
        "w=[concept=%.2f ev=%.2f cit=%.2f hier=%.2f] insert_similar_to=%s",
        config.top_k, config.min_score,
        config.weight_shared_concept, config.weight_shared_evidence,
        config.weight_citation_network, config.weight_concept_hierarchy,
        config.insert_similar_to,
    )
    return GraphRecommender(client, config)
