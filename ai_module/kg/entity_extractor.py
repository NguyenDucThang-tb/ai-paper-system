"""
ai_module/kg/entity_extractor.py

Trích xuất thực thể từ UnifiedDocument → ExtractedEntities.
Input chính:
    - doc.authors:  list[str] raw  → AuthorEntity  (regex + LLM fallback)
    - doc.sections: list[Section]  → Method / Dataset / Task  (LLM)
    - doc.abstract: str            → TaskEntity fallback

LLM backend có thể switch giữa Anthropic (production) và Ollama (local/dev)
bằng cách inject LLMBackend khác nhau vào EntityExtractor.

Requires:
    pip install anthropic>=0.25.0
    pip install httpx>=0.27.0   (cho OllamaBackend)

Changelog:
    v2 — 2025-05
        [fix-1] seen_names dedup dùng normalized key (strip -_space) để catch alias
        [fix-2] _get_sections dùng startswith thay vì word-boundary regex
                để tránh \bexperiment\b không match "experiments"
        [fix-3] _call_llm truncate tại sentence boundary thay vì cắt cứng
        [fix-4] section-weighted confidence thay vì giá trị cố định
        [fix-5] LLMBackend có @property model, không access _model trực tiếp
        [fix-6] MethodEntity/DatasetEntity/TaskEntity nhận source_paper từ doc.doc_id
        [fix-7] Tách dataclass sang entities.py — tránh circular import với graph_builder
        [fix-8] _make_fake_section chuyển lên trước class EntityExtractor
        [fix-9] Guard doc.tables với getattr để tránh AttributeError
        [fix-10] _PROMPT_TASKS thêm {section_type} cho nhất quán
        [fix-11] Thêm retry với exponential backoff cho LLM call
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from ingestion.schema.document_schema import UnifiedDocument, Section

# [fix-7] Import từ entities.py thay vì graph_builder.py để tránh circular import
from ai_module.kg.entities import (
    AuthorEntity,
    DatasetEntity,
    ExtractedEntities,
    MethodEntity,
    TaskEntity,
    normalize_entity_name,  # public, đã move từ _normalize_entity_name
)

logger = logging.getLogger(__name__)


# =============================================================================
# LLM BACKEND — Strategy pattern
# Switch giữa Anthropic và Ollama bằng cách inject backend khác nhau
# =============================================================================

class LLMBackend(ABC):
    @abstractmethod
    def extract(self, system: str, user: str) -> str:
        """Gọi LLM, trả về response string."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Tên model đang dùng — public, không access _model trực tiếp."""  # [fix-5]


class AnthropicBackend(LLMBackend):
    """
    Production backend — Claude Sonnet qua Anthropic API.
    Yêu cầu: ANTHROPIC_API_KEY trong env.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 1024,
    ) -> None:
        try:
            import anthropic
            self._client = anthropic.Anthropic()
        except ImportError:
            raise ImportError("pip install anthropic>=0.25.0")
        self._model = model
        self._max_tokens = max_tokens

    @property
    def model(self) -> str:  # [fix-5]
        return self._model

    def extract(self, system: str, user: str) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text


class OllamaBackend(LLMBackend):
    """
    Local/dev backend — Ollama (Qwen2.5, Llama3, ...).
    Yêu cầu: Ollama đang chạy tại base_url.
    """

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def model(self) -> str:  # [fix-5]
        return self._model

    def extract(self, system: str, user: str) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        resp = httpx.post(
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


# =============================================================================
# AUTHOR PARSER — regex-based, không cần LLM
# =============================================================================

# Patterns theo thứ tự độ phổ biến trong paper Việt Nam
_AUTHOR_PATTERNS: list[tuple[str, re.Pattern]] = [
    # "Nguyễn Văn A (Đại học Quốc gia Hà Nội)"
    ("paren", re.compile(
        r"^(?P<name>[^(]+?)\s*\((?P<affil>[^)]+)\)\s*$"
    )),
    # "Tran Thi B, VNU-HCM"  hoặc  "Tran Thi B - VNU"
    ("comma_dash", re.compile(
        r"^(?P<name>[^,\-]+?)\s*[,\-]\s*(?P<affil>.+)$"
    )),
    # "Nguyễn Văn A¹"  hoặc  "Nguyễn Văn A1"  (superscript từ PDF parse)
    ("superscript", re.compile(
        r"^(?P<name>[^\d¹²³⁴⁵]+?)\s*[\d¹²³⁴⁵,]+\s*$"
    )),
]

# Email pattern
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")

# Heuristic nhận diện institution type
_INST_KEYWORDS: dict[str, str] = {
    "university":  "university",
    "đại học":     "university",
    "trường":      "university",
    "institute":   "institute",
    "viện":        "institute",
    "company":     "company",
    "corporation": "company",
    "corp":        "company",
    "ltd":         "company",
    "co.":         "company",
}

# Heuristic nhận diện country từ affiliation
_COUNTRY_KEYWORDS: dict[str, str] = {
    "vietnam":        "VN",
    "việt nam":       "VN",
    "vnu":            "VN",
    "hust":           "VN",
    "hcmut":          "VN",
    "đại học":        "VN",   # ← thêm
    "đh quốc gia":   "VN",   # ← thêm
    "học viện":       "VN",   # ← thêm
    "usa":            "US",
    "united states":  "US",
    "japan":          "JP",
    "china":          "CN",
    "korea":          "KR",
}


# normalize_entity_name đã được move vào entities.py và import ở trên
# Giữ alias nội bộ để không phải đổi tất cả call site bên dưới
_normalize_entity_name = normalize_entity_name


def _parse_author_string(raw: str) -> AuthorEntity:
    """
    Parse 1 author string raw → AuthorEntity.
    Thử regex theo thứ tự pattern, fallback về name-only nếu không match.
    """
    raw = raw.strip()

    # Extract email trước nếu có, rồi loại khỏi string
    email_match = _EMAIL_RE.search(raw)
    email = email_match.group(0) if email_match else None
    if email:
        raw = raw.replace(email, "").strip(" ,;")

    name = raw
    affiliation = None

    for _pname, pattern in _AUTHOR_PATTERNS:
        m = pattern.match(raw)
        if m:
            name = m.group("name").strip()
            affiliation = m.group("affil").strip() if "affil" in pattern.groupindex else None
            break

    # Infer institution_type và country từ affiliation
    inst_type = None
    country = None
    if affiliation:
        aff_lower = affiliation.lower()
        for kw, itype in _INST_KEYWORDS.items():
            if kw in aff_lower:
                inst_type = itype
                break
        for kw, ccode in _COUNTRY_KEYWORDS.items():
            if kw in aff_lower:
                country = ccode
                break

    return AuthorEntity(
        name=name,
        affiliation=affiliation,
        email=email,
        country=country,
        institution_type=inst_type,
    )


def parse_authors(raw_authors: list[str]) -> list[AuthorEntity]:
    """
    Parse list[str] raw từ UnifiedDocument.authors → list[AuthorEntity].
    Đây là entry point cho author extraction — không cần LLM.
    """
    result = []
    for raw in raw_authors:
        if not raw.strip():
            continue
        try:
            entity = _parse_author_string(raw)
            result.append(entity)
        except Exception:
            logger.warning("parse_authors: không parse được '%s', dùng name-only", raw)
            result.append(AuthorEntity(name=raw.strip()))
    return result


# =============================================================================
# SECTION-WEIGHTED CONFIDENCE  [fix-4]
# Entity extract từ section có độ tin cậy cao hơn sẽ nhận confidence cao hơn.
# Key là prefix — match bằng startswith để bắt "methodology", "results", v.v.
# =============================================================================

_SECTION_CONFIDENCE: dict[str, float] = {
    "method":       0.90,
    "methodology":  0.90,
    "approach":     0.88,
    "model":        0.88,
    "proposed":     0.88,
    "experiment":   0.85,
    "evaluation":   0.85,
    "result":       0.83,
    "abstract":     0.75,
    "introduction": 0.70,
    "table_caption": 0.76,  # slightly lower — inferred từ caption
}

_DEFAULT_CONFIDENCE = 0.80


def _section_confidence(section_type: str) -> float:
    """
    Trả về confidence theo section type.  [fix-4]
    So sánh prefix case-insensitive; fallback về _DEFAULT_CONFIDENCE.
    """
    stype = (section_type or "").lower().strip()
    for key, conf in _SECTION_CONFIDENCE.items():
        if stype.startswith(key):
            return conf
    return _DEFAULT_CONFIDENCE


# =============================================================================
# LLM PROMPTS
# =============================================================================

_SYSTEM_EXTRACT = """Bạn là hệ thống trích xuất thực thể từ bài báo khoa học tiếng Việt.
Nhiệm vụ: đọc đoạn văn được cung cấp và trích xuất thực thể theo yêu cầu.
Chỉ trả về JSON hợp lệ, không có text thêm, không có markdown backtick.
Nếu không tìm thấy thực thể nào, trả về list rỗng [].
Tất cả tên phương pháp và dataset phải viết thường (lowercase)."""

_PROMPT_METHODS = """Từ đoạn văn sau (section: {section_type}), hãy trích xuất tất cả PHƯƠNG PHÁP (methods) được đề cập.

Đoạn văn:
{content}

Trả về JSON array. Mỗi phần tử có dạng:
{{
  "name": "tên canonical lowercase, VD: phobert, bilstm-crf, transformer",
  "category": "pretrained_lm | sequence_labeling | generative | classical | other",
  "aliases": ["tên khác nếu có"],
  "based_on": ["tên method cha nếu có, VD: bert khi dùng phobert"],
  "evidence": "câu văn gốc chứng minh method này được dùng (tối đa 200 ký tự)"
}}"""

_PROMPT_DATASETS = """Từ đoạn văn sau (section: {section_type}), hãy trích xuất tất cả DATASET được đề cập.

Đoạn văn:
{content}

Trả về JSON array. Mỗi phần tử có dạng:
{{
  "name": "tên dataset lowercase, VD: vlsp2016, uit-vsfc, phonner",
  "language": "vi | en | multilingual",
  "aliases": ["tên khác nếu có"],
  "metric": "kết quả đo được nếu có, VD: F1=92.3",
  "evidence": "câu văn gốc chứng minh dataset này được dùng (tối đa 200 ký tự)"
}}"""

# [fix-10] Thêm {section_type} cho nhất quán với 2 prompt còn lại
_PROMPT_TASKS = """Từ đoạn văn sau (section: {section_type}), hãy trích xuất TÁC VỤ NLP (tasks) mà bài báo này giải quyết.

Đoạn văn:
{content}

Trả về JSON array. Mỗi phần tử có dạng:
{{
  "name": "tên tác vụ lowercase chuẩn, VD: named entity recognition, sentiment analysis, machine translation",
  "evidence": "câu văn gốc (tối đa 200 ký tự)"
}}"""


# =============================================================================
# HELPERS nội bộ — đặt trước class để tránh confusion  [fix-8]
# =============================================================================

def _make_fake_section(content: str, section_type: str) -> Section:
    """Tạo Section object tạm từ raw text — dùng khi không có section thực."""
    return Section(
        name=section_type,
        content=content,
        order=0,
        section_type=section_type,
    )


# =============================================================================
# ENTITY EXTRACTOR
# =============================================================================

class EntityExtractor:
    """
    Trích xuất thực thể từ UnifiedDocument → ExtractedEntities.

    Cách dùng:
        # Production
        llm = AnthropicBackend(model="claude-sonnet-4-20250514")
        extractor = EntityExtractor(llm)

        # Local dev
        llm = OllamaBackend(model="qwen2.5:7b")
        extractor = EntityExtractor(llm)

        # Extract
        entities = extractor.extract(doc)
    """

    # [fix-2] Dùng startswith trong _get_sections — không dùng \bword\b regex
    # để tránh \bexperiment\b không match "experiments"
    _METHOD_SECTIONS  = {"method", "methodology", "approach", "model", "proposed"}
    _DATASET_SECTIONS = {"experiment", "evaluation", "result"}
    _TASK_SECTIONS    = {"abstract", "introduction"}

    # Retry config cho LLM call  [fix-11]
    _MAX_RETRIES  = 2
    _RETRY_DELAYS = [1.0, 3.0]  # exponential backoff: 1s → 3s

    def __init__(
        self,
        llm: LLMBackend,
        max_section_chars: int = 5000,  # tăng từ 3000 lên 5000 để giảm mất context
    ) -> None:
        """
        Args:
            llm:               LLM backend (Anthropic hoặc Ollama)
            max_section_chars: cắt section nếu quá dài để tránh vượt context window
        Note:
            confidence_llm đã bỏ — giờ dùng _section_confidence() per-section  [fix-4]
        """
        self._llm = llm
        self._max_chars = max_section_chars

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def extract(self, doc: UnifiedDocument) -> ExtractedEntities:
        """
        Extract toàn bộ entity từ 1 UnifiedDocument.
        Author dùng regex, Method/Dataset/Task dùng LLM.
        """
        logger.info("EntityExtractor.extract: title='%s'", doc.title)

        authors  = self._extract_authors(doc)
        methods  = self._extract_methods(doc)
        datasets = self._extract_datasets(doc)
        tasks    = self._extract_tasks(doc)

        logger.info(
            "EntityExtractor.extract: done — authors=%d methods=%d datasets=%d tasks=%d",
            len(authors), len(methods), len(datasets), len(tasks),
        )
        return ExtractedEntities(
            authors=authors,
            methods=methods,
            datasets=datasets,
            tasks=tasks,
        )

    # ------------------------------------------------------------------
    # Author — regex only
    # ------------------------------------------------------------------

    def _extract_authors(self, doc: UnifiedDocument) -> list[AuthorEntity]:
        if not doc.authors:
            logger.warning("_extract_authors: doc.authors rỗng — title='%s'", doc.title)
            return []
        return parse_authors(doc.authors)

    # ------------------------------------------------------------------
    # Method — LLM trên section type "method"
    # ------------------------------------------------------------------

    def _extract_methods(self, doc: UnifiedDocument) -> list[MethodEntity]:
        sections = self._get_sections(doc, self._METHOD_SECTIONS)
        if not sections:
            logger.debug("_extract_methods: không có method section — title='%s'", doc.title)
            return []

        results: list[MethodEntity] = []
        seen_normalized: set[str] = set()  # [fix-1] normalized key thay vì raw name

        for section in sections:
            raw = self._call_llm(
                prompt_template=_PROMPT_METHODS,
                section=section,
            )
            items = self._parse_json_list(raw, context="methods")
            stype = section.section_type or section.name
            conf = _section_confidence(stype)  # [fix-4]

            for item in items:
                name = (item.get("name") or "").strip().lower()
                if not name:
                    continue

                # [fix-1] dedup bằng normalized key, không phải raw name
                norm = _normalize_entity_name(name)
                if norm in seen_normalized:
                    continue
                seen_normalized.add(norm)

                # Thêm aliases vào seen để tránh alias của entity này lọt vào sau
                for alias in (item.get("aliases") or []):
                    seen_normalized.add(_normalize_entity_name(alias))

                results.append(MethodEntity(
                    name=name,
                    category=item.get("category"),
                    aliases=item.get("aliases") or [],
                    source_paper=getattr(doc, "doc_id", None),  # [fix-6]
                    source_section=stype,
                    confidence=conf,                             # [fix-4]
                    evidence=(item.get("evidence") or "")[:200],
                    based_on=item.get("based_on") or [],
                ))

        return results

    # ------------------------------------------------------------------
    # Dataset — LLM trên section type "experiment"
    # ------------------------------------------------------------------

    def _extract_datasets(self, doc: UnifiedDocument) -> list[DatasetEntity]:
        sections = self._get_sections(doc, self._DATASET_SECTIONS)

        # [fix-9] Guard doc.tables với getattr để tránh AttributeError
        # nếu UnifiedDocument không có field tables hoặc tables = None
        table_texts = [
            t.caption
            for t in getattr(doc, "tables", None) or []
            if t.caption and t.caption.strip()
        ]

        if not sections and not table_texts:
            logger.debug("_extract_datasets: không có experiment section — title='%s'", doc.title)
            return []

        results: list[DatasetEntity] = []
        seen_normalized: set[str] = set()  # [fix-1]

        for section in sections:
            raw = self._call_llm(
                prompt_template=_PROMPT_DATASETS,
                section=section,
            )
            items = self._parse_json_list(raw, context="datasets")
            stype = section.section_type or section.name
            conf = _section_confidence(stype)  # [fix-4]

            for item in items:
                name = (item.get("name") or "").strip().lower()
                if not name:
                    continue

                norm = _normalize_entity_name(name)  # [fix-1]
                if norm in seen_normalized:
                    continue
                seen_normalized.add(norm)
                for alias in (item.get("aliases") or []):
                    seen_normalized.add(_normalize_entity_name(alias))

                results.append(DatasetEntity(
                    name=name,
                    language=item.get("language"),
                    aliases=item.get("aliases") or [],
                    source_paper=getattr(doc, "doc_id", None),  # [fix-6]
                    source_section=stype,
                    confidence=conf,                             # [fix-4]
                    evidence=(item.get("evidence") or "")[:200],
                    metric=item.get("metric"),
                ))

        # Extract từ table captions nếu chưa có
        if table_texts:
            combined = " ".join(table_texts)[:self._max_chars]
            fake_section = _make_fake_section(combined, "table_caption")
            raw = self._call_llm(_PROMPT_DATASETS, fake_section)
            conf = _section_confidence("table_caption")  # [fix-4]
            for item in self._parse_json_list(raw, context="datasets_table"):
                name = (item.get("name") or "").strip().lower()
                if not name:
                    continue

                norm = _normalize_entity_name(name)  # [fix-1]
                if norm in seen_normalized:
                    continue
                seen_normalized.add(norm)

                results.append(DatasetEntity(
                    name=name,
                    language=item.get("language"),
                    aliases=item.get("aliases") or [],
                    source_paper=getattr(doc, "doc_id", None),  # [fix-6]
                    source_section="table_caption",
                    confidence=conf,                             # [fix-4]
                    evidence=(item.get("evidence") or "")[:200],
                    metric=item.get("metric"),
                ))

        return results

    # ------------------------------------------------------------------
    # Task — LLM trên abstract + introduction
    # ------------------------------------------------------------------

    def _extract_tasks(self, doc: UnifiedDocument) -> list[TaskEntity]:
        sections = self._get_sections(doc, self._TASK_SECTIONS)

        # Fallback: dùng doc.abstract nếu không có section abstract
        # Chỉ thêm nếu chưa có abstract section để tránh duplicate LLM call
        has_abstract_section = any(
            (s.section_type or "").lower().startswith("abstract")
            for s in sections
        )
        if not has_abstract_section and doc.abstract:
            sections = [_make_fake_section(doc.abstract, "abstract")] + list(sections)

        if not sections:
            logger.debug("_extract_tasks: không có abstract/intro — title='%s'", doc.title)
            return []

        results: list[TaskEntity] = []
        seen_normalized: set[str] = set()  # [fix-1]

        for section in sections:
            raw = self._call_llm(
                prompt_template=_PROMPT_TASKS,
                section=section,
            )
            items = self._parse_json_list(raw, context="tasks")
            stype = section.section_type or section.name
            conf = _section_confidence(stype)  # [fix-4]

            for item in items:
                name = (item.get("name") or "").strip().lower()
                if not name:
                    continue

                norm = _normalize_entity_name(name)  # [fix-1]
                if norm in seen_normalized:
                    continue
                seen_normalized.add(norm)

                results.append(TaskEntity(
                    name=name,
                    source_paper=getattr(doc, "doc_id", None),  # [fix-6]
                    source_section=stype,
                    confidence=conf,                             # [fix-4]
                    evidence=(item.get("evidence") or "")[:200],
                ))

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_sections(
        self,
        doc: UnifiedDocument,
        target_types: set[str],
    ) -> list[Section]:
        """
        Lấy sections có section_type bắt đầu bằng bất kỳ key nào trong target_types.

        [fix-2] Dùng startswith thay vì word-boundary regex \b...\b.
        Lý do: re.search(r"\bexperiment\b", "experiments") → None vì \b match
        boundary tại vị trí trước 's', không match được "experiments".
        startswith("experiment") sẽ match cả "experiment" lẫn "experiments".
        """
        result = []
        for s in doc.sections:
            stype = (s.section_type or s.name or "").lower()
            if any(stype.startswith(t) for t in target_types):
                result.append(s)
        return result

    def _call_llm(
        self,
        prompt_template: str,
        section: Section,
    ) -> str:
        """
        Gọi LLM với section content, trả về raw string.
        Truncate tại sentence boundary để tránh cắt đứt context.  [fix-3]
        Retry với exponential backoff khi gặp lỗi tạm thời.       [fix-11]
        """
        content = section.content or ""
        if len(content) > self._max_chars:
            truncated = content[:self._max_chars]
            # [fix-3] tìm dấu chấm cuối cùng trong vùng 80–100% của max_chars
            last_period = truncated.rfind(".")
            if last_period > self._max_chars * 0.8:
                truncated = truncated[:last_period + 1]
            logger.debug(
                "_call_llm: section '%s' truncate %d → %d chars",
                section.name, len(content), len(truncated),
            )
            content = truncated

        user_prompt = prompt_template.format(
            section_type=section.section_type or section.name,
            content=content,
        )

        # [fix-11] Retry với exponential backoff
        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                return self._llm.extract(system=_SYSTEM_EXTRACT, user=user_prompt)
            except Exception as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    delay = self._RETRY_DELAYS[attempt]
                    logger.warning(
                        "_call_llm: attempt %d/%d thất bại section='%s', retry sau %.1fs — %s",
                        attempt + 1, self._MAX_RETRIES + 1,
                        section.name, delay, exc,
                    )
                    time.sleep(delay)
                else:
                    logger.exception(
                        "_call_llm: tất cả %d attempts thất bại section='%s'",
                        self._MAX_RETRIES + 1, section.name,
                    )

        return "[]"

    @staticmethod
    def _parse_json_list(raw: str, context: str = "") -> list[dict]:
        """
        Parse JSON array từ LLM response.
        Strip markdown backtick nếu LLM trả về có bọc code block.
        """
        text = raw.strip()
        # Strip ```json ... ``` hoặc ``` ... ```
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            # LLM đôi khi trả về {"items": [...]} thay vì array thẳng
            if isinstance(data, dict):
                for key in ("items", "results", "entities"):
                    if isinstance(data.get(key), list):
                        return data[key]
            logger.warning("_parse_json_list[%s]: không phải list — %s", context, text[:100])
            return []
        except json.JSONDecodeError:
            logger.warning("_parse_json_list[%s]: JSON parse error — %s", context, text[:100])
            return []


# =============================================================================
# FACTORY — tạo extractor từ config
# =============================================================================

def create_extractor_from_env() -> EntityExtractor:
    """
    Tạo EntityExtractor dựa vào biến môi trường.

    .env:
        LLM_BACKEND=anthropic          # hoặc ollama
        ANTHROPIC_MODEL=claude-sonnet-4-20250514
        OLLAMA_MODEL=qwen2.5:7b
        OLLAMA_BASE_URL=http://localhost:11434
    """
    import os
    backend = os.getenv("LLM_BACKEND", "anthropic").lower()

    if backend == "ollama":
        llm = OllamaBackend(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    else:
        llm = AnthropicBackend(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        )

    # [fix-5] dùng llm.model (public property) thay vì llm._model
    logger.info(
        "EntityExtractor: dùng %s model=%s",
        type(llm).__name__,
        llm.model,
    )
    return EntityExtractor(llm)
