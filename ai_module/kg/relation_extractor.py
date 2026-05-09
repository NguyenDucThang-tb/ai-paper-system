"""
ai_module/kg/relation_extractor.py

Hybrid relation extraction: Rule trước → LLM verify cặp khó.
Output: RelationResult — graph_builder nhận và insert toàn bộ edge.

Toàn bộ edge type trong schema:
    Giai đoạn 1 (rule-only, không cần LLM):
        (Author)  -[:WROTE]->          (Paper)
        (Paper)   -[:PUBLISHED_AT]->   (Venue)
        (Paper)   -[:HAS_TOPIC]->      (Topic)
        (Paper)   -[:CITES]->          (Paper)

    Giai đoạn 2 (hybrid — rule detect, LLM verify):
        (Paper)   -[:USES_METHOD]->    (Method)
        (Paper)   -[:EVALUATES_ON]->   (Dataset)
        (Paper)   -[:ADDRESSES_TASK]-> (Task)
        (Method)  -[:BASED_ON]->       (Method)

graph_builder.py nhận RelationResult và gọi neo4j_client để insert.

Changelog:
    v2 — 2025-05
        [fix-1] Import entities từ entities.py thay vì graph_builder — tránh circular import
        [fix-2] _normalize_entity_name import từ entities.py (đã move khỏi entity_extractor)
        [fix-3] Thêm field based_on vào RelationResult + uncomment BASED_ON logic
        [fix-4] LLM fallback cap confidence xuống dưới threshold thay vì confirm vô điều kiện
        [fix-5] doc.journal dùng getattr guard nhất quán với các field khác
        [fix-6] Citation confidence 0.6 thêm minimum title length check
        [fix-7] Log reference based_on đã có field thực — không còn AttributeError
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from ingestion.schema.document_schema import UnifiedDocument

# [fix-1] Import entities từ entities.py, không phải graph_builder
# [fix-2] _normalize_entity_name đã được move vào entities.py
from ai_module.kg.entities import (
    AuthorEntity,
    DatasetEntity,
    ExtractedEntities,
    MethodEntity,
    TaskEntity,
    normalize_entity_name,  # [fix-2] không còn import private _func từ entity_extractor
)
from ai_module.kg.entity_extractor import LLMBackend

logger = logging.getLogger(__name__)

# Minimum title length để accept citation fuzzy match (tránh title quá ngắn/generic)
_MIN_CITATION_TITLE_LEN = 20  # [fix-6]


# =============================================================================
# RELATION DATACLASSES — contract với graph_builder.py
# =============================================================================

@dataclass
class WroteRelation:
    """(Author)-[:WROTE {order}]->(Paper)"""
    author_id: str
    paper_id:  str
    order:     int


@dataclass
class PublishedAtRelation:
    """(Paper)-[:PUBLISHED_AT]->(Venue)"""
    paper_id:   str
    venue_name: str
    year:       Optional[int] = None
    venue_type: str           = "journal"
    publisher:  Optional[str] = None
    volume:     Optional[str] = None
    issue:      Optional[str] = None
    pages:      Optional[str] = None


@dataclass
class HasTopicRelation:
    """(Paper)-[:HAS_TOPIC]->(Topic)"""
    paper_id:   str
    topic_name: str
    source:     str = "keyword"   # "keyword" | "llm_extracted"


@dataclass
class CitesRelation:
    """(Paper)-[:CITES]->(Paper)"""
    citing_paper_id: str
    cited_doi:       Optional[str] = None
    cited_title:     Optional[str] = None
    cited_year:      Optional[int] = None
    raw_ref_text:    str           = ""
    confidence:      float         = 1.0


@dataclass
class UsesMethodRelation:
    """(Paper)-[:USES_METHOD]->(Method)"""
    paper_id:       str
    method_name:    str
    source_section: str   = "method"
    confidence:     float = 1.0
    evidence:       str   = ""


@dataclass
class EvaluatesOnRelation:
    """(Paper)-[:EVALUATES_ON]->(Dataset)"""
    paper_id:       str
    dataset_name:   str
    source_section: str           = "experiment"
    confidence:     float         = 1.0
    evidence:       str           = ""
    metric:         Optional[str] = None


@dataclass
class AddressesTaskRelation:
    """(Paper)-[:ADDRESSES_TASK]->(Task)"""
    paper_id:       str
    task_name:      str
    source_section: str   = "abstract"
    confidence:     float = 1.0
    evidence:       str   = ""


@dataclass
class BasedOnRelation:
    """(Method)-[:BASED_ON]->(Method)"""
    child_method:  str
    parent_method: str
    confidence:    float = 1.0


@dataclass
class RelationResult:
    # Giai đoạn 1 — rule-only
    wrote:        list[WroteRelation]       = field(default_factory=list)
    published_at: list[PublishedAtRelation] = field(default_factory=list)
    has_topic:    list[HasTopicRelation]    = field(default_factory=list)
    cites:        list[CitesRelation]       = field(default_factory=list)

    # Giai đoạn 2 — hybrid
    uses_method:    list[UsesMethodRelation]    = field(default_factory=list)
    evaluates_on:   list[EvaluatesOnRelation]   = field(default_factory=list)
    addresses_task: list[AddressesTaskRelation] = field(default_factory=list)
    based_on:       list[BasedOnRelation]       = field(default_factory=list)  # [fix-3]

    def summary(self) -> str:
        """Log-friendly summary."""
        return (
            f"wrote={len(self.wrote)} published_at={len(self.published_at)} "
            f"has_topic={len(self.has_topic)} cites={len(self.cites)} "
            f"uses_method={len(self.uses_method)} evaluates_on={len(self.evaluates_on)} "
            f"addresses_task={len(self.addresses_task)} based_on={len(self.based_on)}"
        )


# =============================================================================
# RULE EXTRACTOR — detect candidate pairs từ text + entity list
# =============================================================================

# Verb patterns gợi ý USES_METHOD relation
_RE_METHOD_USE = re.compile(
    r"(?:s[uử][\s]*d[uụ]ng|áp\s+d[uụ]ng|đ[eề]\s+xu[aấ]t|propose[sd]?|use[sd]?|apply|appli(?:es|ed)|adopt(?:ed)?|employ(?:ed)?|fine[\s\-]tun(?:e[sd]?|ing)|pre[\s\-]train(?:ed)?)",
    re.IGNORECASE,
)

# Verb patterns gợi ý EVALUATES_ON relation
_RE_DATASET_EVAL = re.compile(
    r"(?:đánh\s+giá|thử\s+nghiệm|thực\s+nghiệm|evaluate[sd]?|experiment(?:ed)?|test(?:ed)?|benchmark(?:ed)?|train(?:ed)?\s+on|evaluat(?:e|es|ed|ing)\s+on)",
    re.IGNORECASE,
)

# Verb patterns gợi ý ADDRESSES_TASK
_RE_TASK_ADDRESS = re.compile(
    r"(?:gi[aả]i\s+quy[eế]t|x[uử]\s+l[yý]|giải\s+quyết|address(?:es|ed)?|solv(?:e[sd]?|ing)|tackl(?:e[sd]?|ing)|focus(?:es|ed)?\s+on|aim[s]?\s+(?:to|at))",
    re.IGNORECASE,
)

# Window tìm kiếm — số chars tối đa giữa entity và verb
# 250 thay vì 150 vì câu học thuật tiếng Việt thường dài hơn tiếng Anh
_COOCCURRENCE_WINDOW = 250

# Batch size khi gọi LLM verify — tránh vượt context window
_LLM_VERIFY_BATCH_SIZE = 10


@dataclass
class _CandidatePair:
    """Cặp relation cần LLM verify."""
    relation_type:   str            # "USES_METHOD" | "EVALUATES_ON" | "ADDRESSES_TASK"
    paper_id:        str
    entity_name:     str
    evidence:        str
    rule_confidence: float
    metric:          Optional[str] = None   # chỉ cho EVALUATES_ON


class RuleRelationExtractor:
    """
    Bước 1: extract relation bằng rule + co-occurrence.
    Trả về candidate pairs với confidence rule-based.
    Các cặp confidence trung bình sẽ được LLM verify ở bước 2.
    """

    _RULE_HIGH_CONFIDENCE = 0.85   # giữ nguyên, không cần LLM
    _RULE_LOW_CONFIDENCE  = 0.50   # dưới ngưỡng này bỏ luôn

    def extract(
        self,
        doc: UnifiedDocument,
        paper_id: str,
        entities: ExtractedEntities,
        author_id_map: dict[str, str],
    ) -> tuple[RelationResult, list[_CandidatePair]]:
        """
        Returns:
            result:     RelationResult với high-confidence relations (không cần LLM)
            candidates: list cặp cần LLM verify (confidence trung bình)
        """
        result = RelationResult()
        candidates: list[_CandidatePair] = []

        full_text = self._build_full_text(doc)

        # ── Giai đoạn 1 — rule-only ───────────────────────────────────────

        # WROTE — từ author_id_map (đã resolve trong graph_builder)
        for order, author in enumerate(entities.authors):
            author_id = author_id_map.get(author.name)
            if author_id:
                result.wrote.append(WroteRelation(
                    author_id=author_id,
                    paper_id=paper_id,
                    order=order,
                ))

        # PUBLISHED_AT — từ metadata
        # [fix-5] dùng getattr nhất quán với các field khác
        journal = getattr(doc, "journal", None)
        if journal:
            result.published_at.append(PublishedAtRelation(
                paper_id=paper_id,
                venue_name=journal,
                year=getattr(doc, "year", None),
                venue_type=self._infer_venue_type(journal),
                publisher=getattr(doc, "publisher", None),
                volume=getattr(doc, "volume", None),
                issue=getattr(doc, "issue", None),
                pages=getattr(doc, "pages", None),
            ))

        # HAS_TOPIC — từ keywords
        for kw in (getattr(doc, "keywords", None) or []):
            kw_norm = kw.lower().strip()
            if kw_norm:
                result.has_topic.append(HasTopicRelation(
                    paper_id=paper_id,
                    topic_name=kw_norm,
                    source="keyword",
                ))

        # CITES — từ references
        # [fix-6] Thêm minimum title length check cho fuzzy match
        for ref in (getattr(doc, "references", None) or []):
            if not ref.doi and not ref.title:
                continue

            # Bỏ qua citation title quá ngắn/generic (< _MIN_CITATION_TITLE_LEN chars)
            if not ref.doi and ref.title and len(ref.title.strip()) < _MIN_CITATION_TITLE_LEN:
                logger.debug(
                    "CITES: bỏ qua title quá ngắn '%s' (< %d chars)",
                    ref.title, _MIN_CITATION_TITLE_LEN,
                )
                continue

            confidence = 1.0 if ref.doi else (0.8 if ref.year else 0.6)
            result.cites.append(CitesRelation(
                citing_paper_id=paper_id,
                cited_doi=getattr(ref, "doi", None),
                cited_title=getattr(ref, "title", None),
                cited_year=getattr(ref, "year", None),
                raw_ref_text=getattr(ref, "raw_text", ""),
                confidence=confidence,
            ))

        # ── Giai đoạn 2 — hybrid ─────────────────────────────────────────

        # USES_METHOD candidates
        for method in entities.methods:
            conf, evidence = self._score_method_relation(method, full_text)
            if conf >= self._RULE_HIGH_CONFIDENCE:
                result.uses_method.append(UsesMethodRelation(
                    paper_id=paper_id,
                    method_name=method.name,
                    source_section=method.source_section,
                    confidence=conf,
                    evidence=evidence,
                ))
            elif conf >= self._RULE_LOW_CONFIDENCE:
                candidates.append(_CandidatePair(
                    relation_type="USES_METHOD",
                    paper_id=paper_id,
                    entity_name=method.name,
                    evidence=evidence,
                    rule_confidence=conf,
                ))

        # EVALUATES_ON candidates
        for dataset in entities.datasets:
            conf, evidence = self._score_dataset_relation(dataset, full_text)
            if conf >= self._RULE_HIGH_CONFIDENCE:
                result.evaluates_on.append(EvaluatesOnRelation(
                    paper_id=paper_id,
                    dataset_name=dataset.name,
                    source_section=dataset.source_section,
                    confidence=conf,
                    evidence=evidence,
                    metric=dataset.metric,
                ))
            elif conf >= self._RULE_LOW_CONFIDENCE:
                candidates.append(_CandidatePair(
                    relation_type="EVALUATES_ON",
                    paper_id=paper_id,
                    entity_name=dataset.name,
                    evidence=evidence,
                    rule_confidence=conf,
                    metric=dataset.metric,
                ))

        # ADDRESSES_TASK candidates
        for task in entities.tasks:
            conf, evidence = self._score_task_relation(task, full_text)
            if conf >= self._RULE_HIGH_CONFIDENCE:
                result.addresses_task.append(AddressesTaskRelation(
                    paper_id=paper_id,
                    task_name=task.name,
                    source_section=task.source_section,
                    confidence=conf,
                    evidence=evidence,
                ))
            elif conf >= self._RULE_LOW_CONFIDENCE:
                candidates.append(_CandidatePair(
                    relation_type="ADDRESSES_TASK",
                    paper_id=paper_id,
                    entity_name=task.name,
                    evidence=evidence,
                    rule_confidence=conf,
                ))

        # BASED_ON — từ MethodEntity.based_on list (đã extract ở entity_extractor)
        # [fix-3] Uncomment và dùng method.confidence thay vì hardcode 1.0
        # vì đây là LLM output, không phải structural fact
        for method in entities.methods:
            for parent in (method.based_on or []):
                result.based_on.append(BasedOnRelation(
                    child_method=method.name,
                    parent_method=parent.lower().strip(),
                    confidence=method.confidence,
                ))

        return result, candidates

    # ── scoring helpers ───────────────────────────────────────────────────

    def _score_method_relation(
        self, method: MethodEntity, full_text: str
    ) -> tuple[float, str]:
        base = method.confidence
        evidence = method.evidence

        _, found_evidence = self._find_cooccurrence(
            full_text, method.name, _RE_METHOD_USE
        )
        if found_evidence:
            evidence = found_evidence
            base = min(1.0, base + 0.10)

        if method.source_section == "method":
            base = min(1.0, base + 0.05)

        return round(base, 3), evidence

    def _score_dataset_relation(
        self, dataset: DatasetEntity, full_text: str
    ) -> tuple[float, str]:
        base = dataset.confidence
        evidence = dataset.evidence

        _, found_evidence = self._find_cooccurrence(
            full_text, dataset.name, _RE_DATASET_EVAL
        )
        if found_evidence:
            evidence = found_evidence
            base = min(1.0, base + 0.10)

        if dataset.metric:
            base = min(1.0, base + 0.05)

        if dataset.source_section == "experiment":
            base = min(1.0, base + 0.05)

        return round(base, 3), evidence

    def _score_task_relation(
        self, task: TaskEntity, full_text: str
    ) -> tuple[float, str]:
        base = task.confidence
        evidence = task.evidence

        _, found_evidence = self._find_cooccurrence(
            full_text, task.name, _RE_TASK_ADDRESS
        )
        if found_evidence:
            evidence = found_evidence
            base = min(1.0, base + 0.10)

        if task.source_section in ("abstract", "introduction"):
            base = min(1.0, base + 0.05)

        return round(base, 3), evidence

    @staticmethod
    def _find_cooccurrence(
        text: str,
        entity_name: str,
        verb_pattern: re.Pattern,
    ) -> tuple[str, str]:
        """
        Tìm đoạn text có cả entity_name và verb trong window _COOCCURRENCE_WINDOW chars.
        Trả về (window_text, evidence_sentence).
        evidence = "" nếu không tìm thấy.

        NOTE: dùng Python built-in .lower() — an toàn với tiếng Việt vì
        .lower() không thay đổi byte offset của ký tự Unicode có dấu.
        KHÔNG thay thế bằng thư viện normalize khác mà không kiểm tra offset.
        """
        text_lower = text.lower()
        entity_lower = entity_name.lower()

        for match in re.finditer(re.escape(entity_lower), text_lower):
            start  = max(0, match.start() - _COOCCURRENCE_WINDOW)
            end    = min(len(text), match.end() + _COOCCURRENCE_WINDOW)
            window = text[start:end]

            if verb_pattern.search(window):
                for line in window.splitlines():
                    if entity_lower in line.lower():
                        return window, line.strip()[:200]
                return window, window[:200]

        return "", ""

    @staticmethod
    def _infer_venue_type(venue_name: str) -> str:
        name_lower = venue_name.lower()
        if any(k in name_lower for k in (
            "conference", "proceedings", "workshop",
            "acl", "emnlp", "naacl", "coling",
        )):
            return "conference"
        if any(k in name_lower for k in ("arxiv", "preprint")):
            return "preprint"
        return "journal"

    @staticmethod
    def _build_full_text(doc: UnifiedDocument) -> str:
        parts = [getattr(doc, "abstract", "") or ""]
        for sec in (getattr(doc, "sections", None) or []):
            parts.append(sec.content or "")
        return "\n".join(p for p in parts if p)


# =============================================================================
# LLM VERIFIER — verify candidate pairs mà rule không chắc
# =============================================================================

_VERIFY_SYSTEM = """\
Bạn là hệ thống xác minh quan hệ giữa bài báo khoa học và entity.
Với mỗi cặp (paper, entity, relation_type), hãy xác minh relation có đúng không.
Trả về JSON array. KHÔNG viết gì ngoài JSON.

Mỗi phần tử:
{
  "relation_type": "USES_METHOD|EVALUATES_ON|ADDRESSES_TASK",
  "entity_name": "tên entity lowercase, giống hệt input",
  "confirmed": true|false,
  "confidence": 0.0-1.0,
  "evidence": "câu văn gốc làm bằng chứng, tối đa 200 ký tự"
}
"""

_VERIFY_USER_TEMPLATE = """\
Bài báo: {title}

Tóm tắt: {abstract}

Hãy xác minh các quan hệ sau:
{candidates_json}

Với mỗi cặp, kiểm tra trong nội dung bài báo xem relation có tồn tại không.
"""


@dataclass
class _VerifyResult:
    relation_type: str
    entity_name:   str
    confirmed:     bool
    confidence:    float
    evidence:      str
    metric:        Optional[str] = None


class LLMRelationVerifier:
    """
    Verify candidate pairs bằng LLM.
    Nhận LLMBackend đã khởi tạo từ ngoài (DI).
    """

    def __init__(self, llm: LLMBackend, confidence_threshold: float = 0.6) -> None:
        self._llm = llm
        self._confidence_threshold = confidence_threshold

    def verify(
        self,
        doc: UnifiedDocument,
        candidates: list[_CandidatePair],
    ) -> list[_VerifyResult]:
        """
        Verify một batch candidates bằng 1 LLM call.
        Caller tự chia batch trước khi gọi — xem RelationExtractor.extract().
        """
        if not candidates:
            return []

        prompt = self._build_prompt(doc, candidates)
        try:
            raw = self._llm.extract(system=_VERIFY_SYSTEM, user=prompt)
            return self._parse_response(raw, candidates)
        except Exception as e:
            logger.warning(
                "LLMRelationVerifier.verify: LLM call thất bại title='%s' error=%s — "
                "fallback: cap confidence xuống dưới threshold cho tất cả candidates",
                doc.title, e,
            )
            # [fix-4] Cap confidence xuống dưới threshold thay vì confirm vô điều kiện.
            # Candidates trong batch là những cặp rule không chắc (0.5–0.85).
            # Khi LLM fail, không nên inject noise vào KG — _merge_verified sẽ filter
            # ra dựa vào confidence < threshold.
            return [
                _VerifyResult(
                    relation_type=c.relation_type,
                    entity_name=c.entity_name,
                    confirmed=True,
                    confidence=min(c.rule_confidence, self._confidence_threshold - 0.01),
                    evidence=c.evidence,
                    metric=c.metric,
                )
                for c in candidates
            ]

    def _build_prompt(
        self,
        doc: UnifiedDocument,
        candidates: list[_CandidatePair],
    ) -> str:
        cands_json = json.dumps(
            [
                {
                    "relation_type": c.relation_type,
                    "entity_name":   c.entity_name,
                    "evidence_hint": c.evidence,
                }
                for c in candidates
            ],
            ensure_ascii=False,
            indent=2,
        )
        return _VERIFY_USER_TEMPLATE.format(
            title=doc.title,
            abstract=(getattr(doc, "abstract", "") or "")[:500],
            candidates_json=cands_json,
        )

    def _parse_response(
        self,
        raw: str,
        candidates: list[_CandidatePair],
    ) -> list[_VerifyResult]:
        # Strip markdown code block nếu LLM trả về có bọc
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```\s*$", "", cleaned.strip(), flags=re.MULTILINE)

        try:
            data = json.loads(cleaned.strip())
            if not isinstance(data, list):
                data = [data]
        except json.JSONDecodeError as e:
            logger.warning("LLMRelationVerifier._parse_response: JSON decode failed — %s", e)
            # [fix-4] Cùng logic fallback — cap confidence dưới threshold
            return [
                _VerifyResult(
                    relation_type=c.relation_type,
                    entity_name=c.entity_name,
                    confirmed=True,
                    confidence=min(c.rule_confidence, self._confidence_threshold - 0.01),
                    evidence=c.evidence,
                    metric=c.metric,
                )
                for c in candidates
            ]

        # Lookup candidates theo (relation_type, normalized_name) để merge metric
        candidate_map = {
            (c.relation_type, normalize_entity_name(c.entity_name)): c  # [fix-2]
            for c in candidates
        }

        results: list[_VerifyResult] = []
        for item in data:
            try:
                rel_type    = str(item.get("relation_type", ""))
                entity_name = str(item.get("entity_name", "")).lower().strip()
                confirmed   = bool(item.get("confirmed", False))
                confidence  = float(item.get("confidence", 0.5))
                evidence    = str(item.get("evidence", ""))[:200]

                # Lấy metric từ candidate gốc (LLM không extract lại)
                orig   = candidate_map.get((rel_type, normalize_entity_name(entity_name)))
                metric = orig.metric if orig else None

                results.append(_VerifyResult(
                    relation_type=rel_type,
                    entity_name=entity_name,
                    confirmed=confirmed,
                    confidence=confidence,
                    evidence=evidence,
                    metric=metric,
                ))
            except Exception as e:
                logger.debug("LLMRelationVerifier: skip malformed item — %s", e)

        return results


# =============================================================================
# RELATION EXTRACTOR — public API
# =============================================================================

class RelationExtractor:
    """
    Public API — orchestrate Rule → LLM verify → merge RelationResult.

    Cách dùng:
        # Production
        llm = AnthropicBackend(model="claude-sonnet-4-20250514")
        extractor = RelationExtractor(llm, confidence_threshold=0.6)

        # Local dev
        llm = OllamaBackend(model="qwen2.5:7b")
        extractor = RelationExtractor(llm)

        # Extract
        relations = extractor.extract(doc, paper_id, entities, author_id_map)
        # relations là RelationResult — truyền thẳng vào GraphBuilder.build()

    author_id_map được tạo trong GraphBuilder sau khi merge_author().
    """

    def __init__(
        self,
        llm: LLMBackend,
        confidence_threshold: float = 0.6,
    ) -> None:
        """
        Args:
            llm:                  LLMBackend đã khởi tạo
            confidence_threshold: confidence tối thiểu để giữ verified relation
        """
        self._confidence_threshold = confidence_threshold
        self._rule     = RuleRelationExtractor()
        self._verifier = LLMRelationVerifier(llm, confidence_threshold)

    def extract(
        self,
        doc: UnifiedDocument,
        paper_id: str,
        entities: ExtractedEntities,
        author_id_map: dict[str, str],
    ) -> RelationResult:
        """
        Extract toàn bộ relation cho 1 paper.

        Args:
            doc:           UnifiedDocument
            paper_id:      UUID của Paper node
            entities:      ExtractedEntities từ entity_extractor.py
            author_id_map: {author_name: author_id} — từ GraphBuilder sau merge_author

        Returns:
            RelationResult chứa tất cả edge cần insert
        """
        logger.info("RelationExtractor.extract: start paper_id=%s", paper_id)

        # Bước 1 — Rule extract + phân loại high/low confidence
        rule_result, candidates = self._rule.extract(
            doc, paper_id, entities, author_id_map
        )

        # [fix-7] Log dùng result.summary() — không còn reference field không tồn tại
        logger.debug("RelationExtractor: rule done — %s | candidates=%d",
                     rule_result.summary(), len(candidates))

        # Bước 2 — LLM verify theo batch
        if candidates:
            total_batches = -(-len(candidates) // _LLM_VERIFY_BATCH_SIZE)  # ceil division
            for i in range(0, len(candidates), _LLM_VERIFY_BATCH_SIZE):
                batch = candidates[i : i + _LLM_VERIFY_BATCH_SIZE]
                logger.debug(
                    "RelationExtractor: LLM verify batch %d/%d (%d candidates)",
                    i // _LLM_VERIFY_BATCH_SIZE + 1,
                    total_batches,
                    len(batch),
                )
                verified = self._verifier.verify(doc, batch)
                self._merge_verified(rule_result, verified, paper_id, entities)
        else:
            logger.debug("RelationExtractor: không có candidate cần LLM verify")

        logger.info("RelationExtractor.extract: done — %s", rule_result.summary())
        return rule_result

    def _merge_verified(
        self,
        result: RelationResult,
        verified: list[_VerifyResult],
        paper_id: str,
        entities: ExtractedEntities,
    ) -> None:
        """
        Thêm verified relations vào result.
        Bỏ qua nếu confirmed=False hoặc confidence < threshold.
        Dedup check dùng normalize_entity_name để bắt alias/variant.
        """
        existing_methods  = {normalize_entity_name(r.method_name)  for r in result.uses_method}
        existing_datasets = {normalize_entity_name(r.dataset_name) for r in result.evaluates_on}
        existing_tasks    = {normalize_entity_name(r.task_name)    for r in result.addresses_task}

        for v in verified:
            if not v.confirmed or v.confidence < self._confidence_threshold:
                logger.debug(
                    "RelationExtractor: bỏ qua '%s' %s — confirmed=%s conf=%.2f",
                    v.entity_name, v.relation_type, v.confirmed, v.confidence,
                )
                continue

            norm = normalize_entity_name(v.entity_name)  # [fix-2]

            if v.relation_type == "USES_METHOD" and norm not in existing_methods:
                source_sec = next(
                    (m.source_section for m in entities.methods
                     if normalize_entity_name(m.name) == norm),
                    "method",
                )
                result.uses_method.append(UsesMethodRelation(
                    paper_id=paper_id,
                    method_name=v.entity_name,
                    source_section=source_sec,
                    confidence=v.confidence,
                    evidence=v.evidence,
                ))
                existing_methods.add(norm)

            elif v.relation_type == "EVALUATES_ON" and norm not in existing_datasets:
                source_sec = next(
                    (d.source_section for d in entities.datasets
                     if normalize_entity_name(d.name) == norm),
                    "experiment",
                )
                result.evaluates_on.append(EvaluatesOnRelation(
                    paper_id=paper_id,
                    dataset_name=v.entity_name,
                    source_section=source_sec,
                    confidence=v.confidence,
                    evidence=v.evidence,
                    metric=v.metric,
                ))
                existing_datasets.add(norm)

            elif v.relation_type == "ADDRESSES_TASK" and norm not in existing_tasks:
                source_sec = next(
                    (t.source_section for t in entities.tasks
                     if normalize_entity_name(t.name) == norm),
                    "abstract",
                )
                result.addresses_task.append(AddressesTaskRelation(
                    paper_id=paper_id,
                    task_name=v.entity_name,
                    source_section=source_sec,
                    confidence=v.confidence,
                    evidence=v.evidence,
                ))
                existing_tasks.add(norm)
