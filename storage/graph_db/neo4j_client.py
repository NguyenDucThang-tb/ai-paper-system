"""
storage/graph_db/neo4j_client.py

Neo4j client cho Paper RAG + Knowledge Graph System.
Implement toàn bộ MERGE template từ neo4j_schema.cypher.
Bám sát UnifiedDocument / Reference schema từ document_schema.py.

Requires:
    pip install neo4j>=5.0.0

Changelog:
    [fix-1] ensure_schema đưa vào trong class Neo4jClient
    [fix-2] merge_method / merge_dataset / merge_task thêm ON MATCH SET confidence
    [fix-3] merge_citation thêm note về title collision khi year=null
    [fix-4] Thêm run_query() — graph_updater.py dùng qua Neo4jClientProtocol
    [fix-5] Thêm lookup_method_by_fulltext() và lookup_dataset_by_fulltext()
            — EntityMerger trong graph_updater.py cần 2 method này
    [fix-6] merge_author KHÔNG raise ValueError khi paper_id không tìm thấy
            — raise làm vỡ toàn bộ batch dù các author khác hợp lệ
            — đổi thành log error + raise Neo4jMergeError (custom) để caller
              có thể catch riêng nếu cần, BatchGraphBuilder vẫn continue_on_error
    [fix-7] merge_paper_by_title_year normalize year=None → 0 (sentinel)
            nhất quán với graph_builder.resolve_paper_id() và schema comment
    [fix-8] merge_institution đổi raise thành log error + raise Neo4jMergeError
            nhất quán với fix-6
"""

from __future__ import annotations

import logging
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Optional

from neo4j import GraphDatabase, Session
from neo4j.exceptions import ServiceUnavailable, TransientError

logger = logging.getLogger(__name__)


# =============================================================================
# CUSTOM EXCEPTION  [fix-6]
# Dùng thay cho ValueError raw để caller có thể catch riêng.
# =============================================================================

class Neo4jMergeError(Exception):
    """
    Raise khi MERGE thất bại vì node prerequisite không tồn tại.
    VD: merge_author() không tìm thấy paper_id.

    Lý do dùng custom exception thay vì ValueError:
        - Caller (graph_builder, BatchGraphBuilder) có thể catch
          Neo4jMergeError riêng mà không accidentally catch ValueError
          từ logic khác (index out of range, bad param, ...)
        - BatchGraphBuilder.continue_on_error sẽ log + continue đúng behavior.
    """


# =============================================================================
# CONFIG
# =============================================================================

@dataclass
class Neo4jConfig:
    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"
    max_connection_pool_size: int = 50
    connection_timeout: float = 30.0
    max_retry_time: float = 30.0


# =============================================================================
# HELPERS
# =============================================================================

def _normalize_name(text: str) -> str:
    """
    Lowercase + bỏ dấu tiếng Việt + collapse whitespace.
    Dùng cho Institution.name (MERGE key) và Topic.name.
    VD: "Đại học Quốc gia Hà Nội" → "dai hoc quoc gia ha noi"
    """
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(ascii_str.lower().split())


def _to_ascii(text: str) -> str:
    """
    Chỉ bỏ dấu, giữ nguyên case — dùng cho name_ascii của Author/Institution
    (lưu vào full-text index, không phải MERGE key).
    """
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _new_id() -> str:
    return str(uuid.uuid4())


# =============================================================================
# CLIENT
# =============================================================================

class Neo4jClient:
    """
    Thread-safe Neo4j client với connection pool.

    Dùng pattern:
        client = Neo4jClient(config)
        client.connect()
        try:
            client.merge_paper(doc)
        finally:
            client.close()

    Hoặc dùng context manager:
        with Neo4jClient(config) as client:
            client.merge_paper(doc)
    """

    def __init__(self, config: Neo4jConfig):
        self._config = config
        self._driver = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._driver = GraphDatabase.driver(
            self._config.uri,
            auth=(self._config.username, self._config.password),
            max_connection_pool_size=self._config.max_connection_pool_size,
            connection_timeout=self._config.connection_timeout,
        )
        self._driver.verify_connectivity()
        logger.info("Neo4j connected: %s", self._config.uri)

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed.")

    def __enter__(self) -> "Neo4jClient":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    @contextmanager
    def _session(self):
        if not self._driver:
            raise RuntimeError("Neo4jClient chưa connect. Gọi client.connect() trước.")
        session: Session = self._driver.session(database=self._config.database)
        try:
            yield session
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Schema setup  [fix-1] đưa vào trong class
    # ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        constraints = [
            "CREATE CONSTRAINT paper_doi_unique IF NOT EXISTS FOR (p:Paper) REQUIRE p.doi IS UNIQUE",
            "CREATE CONSTRAINT paper_id_unique IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT author_id_unique IF NOT EXISTS FOR (a:Author) REQUIRE a.id IS UNIQUE",
            "CREATE CONSTRAINT method_name_unique IF NOT EXISTS FOR (m:Method) REQUIRE m.name IS UNIQUE",
            "CREATE CONSTRAINT dataset_name_unique IF NOT EXISTS FOR (d:Dataset) REQUIRE d.name IS UNIQUE",
            "CREATE CONSTRAINT task_name_unique IF NOT EXISTS FOR (t:Task) REQUIRE t.name IS UNIQUE",
            "CREATE CONSTRAINT topic_name_unique IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
            "CREATE CONSTRAINT venue_name_unique IF NOT EXISTS FOR (v:Venue) REQUIRE v.name IS UNIQUE",
            "CREATE CONSTRAINT institution_name_unique IF NOT EXISTS FOR (i:Institution) REQUIRE i.name IS UNIQUE",
        ]
        for cypher in constraints:
            self.execute_write(cypher)
        logger.info("ensure_schema: constraints OK")

        # Fulltext indexes — cần cho lookup_author/method/dataset_by_fulltext
        fulltext_indexes = [
            "CREATE FULLTEXT INDEX author_ft IF NOT EXISTS FOR (a:Author) ON EACH [a.name, a.name_ascii]",
            "CREATE FULLTEXT INDEX paper_title_ft IF NOT EXISTS FOR (p:Paper) ON EACH [p.title]",
            "CREATE FULLTEXT INDEX method_ft IF NOT EXISTS FOR (m:Method) ON EACH [m.name, m.aliases_text]",
            "CREATE FULLTEXT INDEX dataset_ft IF NOT EXISTS FOR (d:Dataset) ON EACH [d.name, d.aliases_text]",
            "CREATE FULLTEXT INDEX institution_ft IF NOT EXISTS FOR (i:Institution) ON EACH [i.name, i.name_ascii]",
        ]
        for cypher in fulltext_indexes:
            self.execute_write(cypher)
        logger.info("ensure_schema: fulltext indexes OK")

    # ------------------------------------------------------------------
    # Low-level execute helpers
    # Retry TransientError được xử lý tự động bởi Neo4j driver
    # thông qua session.execute_write (managed transaction).
    # KHÔNG dùng session.run() trực tiếp — sẽ mất retry.
    # ------------------------------------------------------------------

    def execute_write(self, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        params = params or {}
        with self._session() as session:
            result = session.execute_write(lambda tx: list(tx.run(query, params)))
            return [dict(r) for r in result]

    def execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        params = params or {}
        with self._session() as session:
            result = session.execute_read(lambda tx: list(tx.run(query, params)))
            return [dict(r) for r in result]

    def run_query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """
        Generic query method — dùng bởi graph_updater.py qua Neo4jClientProtocol.  [fix-4]

        Dùng execute_write vì graph_updater chủ yếu SET/MERGE.
        Nếu cần read-only (MATCH + RETURN), vẫn an toàn — Neo4j driver
        không phân biệt write/read transaction với Cypher read-only.

        NOTE: Nếu sau này cần tối ưu read performance, có thể check
        cypher.strip().upper().startswith("MATCH") để route sang execute_read.
        """
        return self.execute_write(cypher, params)

    # ------------------------------------------------------------------
    # SECTION 6 MERGE TEMPLATES — Giai đoạn 1
    # ------------------------------------------------------------------

    # ── Paper ──────────────────────────────────────────────────────────

    def merge_paper_by_doi(
        self,
        *,
        paper_id: str,
        doi: str,
        title: str,
        year: Optional[int],
        abstract: str = "",
        language: str = "vi",
        source_file: str = "",
        source_type: str = "",
        citation_count: Optional[int] = None,
        chunk_ids: list[str] | None = None,
        page_count: Optional[int] = None,
    ) -> None:
        """
        MERGE paper theo doi.
        Schema cảnh báo: KHÔNG BAO GIỜ gọi hàm này khi doi = None / "".
        Kiểm tra doi ở tầng gọi (graph_builder.py).
        """
        assert doi, "merge_paper_by_doi: doi không được rỗng"

        query = """
        MERGE (p:Paper {doi: $doi})
        ON CREATE SET
            p.id                = $id,
            p.title             = $title,
            p.year              = $year,
            p.abstract          = $abstract,
            p.language          = $language,
            p.source_file       = $source_file,
            p.source_type       = $source_type,
            p.page_count        = $page_count,
            p.citation_count    = $citation_count,
            p.chunk_ids         = $chunk_ids,
            p.processing_status = 'parsed',
            p.created_at        = datetime()
        ON MATCH SET
            p.chunk_ids         = $chunk_ids,
            p.processing_status = 'parsed'
        """
        self.execute_write(query, {
            "doi":            doi,
            "id":             paper_id,
            "title":          title,
            "year":           year,
            "abstract":       abstract,
            "language":       language,
            "source_file":    source_file,
            "source_type":    source_type,
            "page_count":     page_count,
            "citation_count": citation_count,
            "chunk_ids":      chunk_ids or [],
        })
        logger.debug("merge_paper_by_doi: doi=%s", doi)

    def merge_paper_by_title_year(
        self,
        *,
        paper_id: str,
        title: str,
        year: Optional[int],
        language: str = "vi",
        source_file: str = "",
        source_type: str = "",
        chunk_ids: list[str] | None = None,
        page_count: Optional[int] = None,
    ) -> None:
        """
        Fallback MERGE khi doi = None.
        MERGE key: (title, year).

        [fix-7] year=None → normalize thành 0 (sentinel) trước khi MERGE.
        Lý do: Neo4j MERGE (p {title: "X", year: null}) sẽ match tất cả paper
        không rõ năm có cùng title → collision silent.
        Dùng 0 làm sentinel để tránh collision, nhất quán với resolve_paper_id().

        CẢNH BÁO: 2 paper khác nhau cùng title và không rõ năm sẽ bị merge
        thành 1 node. graph_builder.py nên check title length >= 10 trước khi
        gọi hàm này.
        """
        # [fix-7] normalize year sentinel
        year_safe = year if year is not None else 0

        query = """
        MERGE (p:Paper {title: $title, year: $year})
        ON CREATE SET
            p.id                = $id,
            p.language          = $language,
            p.source_file       = $source_file,
            p.source_type       = $source_type,
            p.page_count        = $page_count,
            p.chunk_ids         = $chunk_ids,
            p.processing_status = 'parsed',
            p.created_at        = datetime()
        ON MATCH SET
            p.chunk_ids         = $chunk_ids,
            p.processing_status = CASE
                WHEN p.processing_status = 'stub' THEN 'parsed'
                ELSE p.processing_status
            END
        """
        self.execute_write(query, {
            "title":       title,
            "year":        year_safe,  # [fix-7]
            "id":          paper_id,
            "language":    language,
            "source_file": source_file,
            "source_type": source_type,
            "page_count":  page_count,
            "chunk_ids":   chunk_ids or [],
        })
        logger.debug("merge_paper_by_title_year: title=%s year=%s", title, year_safe)

    def merge_paper(self, doc_dict: dict) -> None:
        """
        Entry point cho graph_builder.py.
        Tự động chọn strategy doi vs title+year theo schema rule.

        doc_dict keys tương ứng field của UnifiedDocument:
            id, title, year, doi, abstract, language,
            source_file, source_type, page_count,
            citation_count, chunk_ids
        """
        doi = doc_dict.get("doi") or ""
        if doi.strip():
            self.merge_paper_by_doi(
                paper_id=doc_dict["id"],
                doi=doi.strip(),
                title=doc_dict.get("title", "Unknown"),
                year=doc_dict.get("year"),
                abstract=doc_dict.get("abstract", ""),
                language=doc_dict.get("language", "vi"),
                source_file=doc_dict.get("source_file", ""),
                source_type=doc_dict.get("source_type", ""),
                citation_count=doc_dict.get("citation_count"),
                chunk_ids=doc_dict.get("chunk_ids", []),
                page_count=doc_dict.get("page_count"),
            )
        else:
            self.merge_paper_by_title_year(
                paper_id=doc_dict["id"],
                title=doc_dict.get("title", "Unknown"),
                year=doc_dict.get("year"),   # merge_paper_by_title_year tự normalize
                language=doc_dict.get("language", "vi"),
                source_file=doc_dict.get("source_file", ""),
                source_type=doc_dict.get("source_type", ""),
                chunk_ids=doc_dict.get("chunk_ids", []),
                page_count=doc_dict.get("page_count"),
            )

    # ── Citation stub ───────────────────────────────────────────────────
    # NOTE: merge_citation_stub() đã bị xoá sau fix Lỗi 2.
    # Stub MERGE và CITES edge hiện được gộp vào 1 transaction trong merge_citation()
    # để tránh race condition giữa 2 execute_write liên tiếp.

    # ── Author ──────────────────────────────────────────────────────────

    def lookup_author_by_fulltext(
        self,
        name: str,
        affiliation: Optional[str] = None,
        threshold: float = 0.8,
    ) -> Optional[str]:
        """
        Full-text search author trước khi CREATE.
        Trả về author_id nếu tìm thấy match đủ confidence, None nếu không.
        Schema note: dùng index author_ft trên (name, name_ascii).
        """
        query_str = name.strip()
        if affiliation and affiliation.strip():
            query_str = f"{query_str} {affiliation.strip()}"

        query = """
        CALL db.index.fulltext.queryNodes('author_ft', $query_str)
        YIELD node, score
        WHERE score >= $threshold
        RETURN node.id AS id, node.name AS name, score
        ORDER BY score DESC
        LIMIT 1
        """
        results = self.execute_read(query, {
            "query_str": query_str,
            "threshold": threshold,
        })
        if results:
            logger.debug(
                "lookup_author_by_fulltext: found '%s' score=%.2f",
                results[0]["name"], results[0]["score"]
            )
            return results[0]["id"]
        return None

    def merge_author(
        self,
        *,
        author_id: str,
        name: str,
        paper_id: str,
        order: int,
        email: Optional[str] = None,
        affiliation: Optional[str] = None,
    ) -> None:
        """
        MERGE Author bằng UUID id (không unique theo name).
        Tạo edge (Author)-[:WROTE {order}]->(Paper).

        [fix-6] KHÔNG raise ValueError khi paper_id không tìm thấy.
        Lý do: raise làm vỡ toàn bộ batch khi build_phase1() loop qua nhiều author.
        Thay bằng raise Neo4jMergeError để caller (graph_builder) có thể catch
        riêng nếu cần — BatchGraphBuilder.continue_on_error sẽ xử lý đúng.
        """
        name_ascii = _to_ascii(name)
        query = """
        MERGE (a:Author {id: $author_id})
        ON CREATE SET
            a.name        = $name,
            a.name_ascii  = $name_ascii,
            a.email       = $email,
            a.affiliation = $affiliation
        WITH a
        MATCH (p:Paper {id: $paper_id})
        MERGE (a)-[:WROTE {order: $order}]->(p)
        RETURN p.id AS paper_found
        """
        result = self.execute_write(query, {
            "author_id":   author_id,
            "name":        name,
            "name_ascii":  name_ascii,
            "email":       email,
            "affiliation": affiliation,
            "paper_id":    paper_id,
            "order":       order,
        })
        if not result:
            # [fix-6] log error + raise Neo4jMergeError thay vì ValueError
            logger.error(
                "merge_author: paper_id='%s' không tồn tại trong Neo4j. "
                "Đảm bảo merge_paper() đã chạy trước. Author '%s' không được link.",
                paper_id, name,
            )
            raise Neo4jMergeError(
                f"merge_author: paper_id '{paper_id}' không tìm thấy — "
                f"author '{name}' không được link vào graph."
            )

    # ── Institution ─────────────────────────────────────────────────────

    def merge_institution(
        self,
        *,
        author_id: str,
        display_name: str,
        country: Optional[str] = None,
        inst_type: Optional[str] = None,
    ) -> None:
        """
        MERGE Institution theo name normalized (lowercase + bỏ dấu).
        Tạo edge (Author)-[:AFFILIATED_WITH]->(Institution).

        [fix-8] Đổi raise ValueError → raise Neo4jMergeError nhất quán với fix-6.
        """
        name_normalized = _normalize_name(display_name)
        name_ascii = _to_ascii(display_name)
        query = """
        MERGE (i:Institution {name: $name_normalized})
        ON CREATE SET
            i.id           = randomUUID(),
            i.display_name = $display_name,
            i.name_ascii   = $name_ascii,
            i.country      = $country,
            i.type         = $inst_type
        WITH i
        MATCH (a:Author {id: $author_id})
        MERGE (a)-[:AFFILIATED_WITH]->(i)
        RETURN a.id AS author_found
        """
        result = self.execute_write(query, {
            "name_normalized": name_normalized,
            "display_name":    display_name,
            "name_ascii":      name_ascii,
            "country":         country,
            "inst_type":       inst_type,
            "author_id":       author_id,
        })
        if not result:
            # [fix-8] nhất quán với fix-6
            logger.error(
                "merge_institution: author_id='%s' không tồn tại trong Neo4j. "
                "Đảm bảo merge_author() đã chạy trước. Institution '%s' không được link.",
                author_id, display_name,
            )
            raise Neo4jMergeError(
                f"merge_institution: author_id '{author_id}' không tìm thấy — "
                f"institution '{display_name}' không được link."
            )

    # ── Venue ───────────────────────────────────────────────────────────

    def merge_venue(
        self,
        *,
        paper_id: str,
        venue_name: str,
        venue_type: str = "journal",
        publisher: Optional[str] = None,
        volume: Optional[str] = None,
        issue: Optional[str] = None,
        pages: Optional[str] = None,
    ) -> None:
        """
        MERGE Venue theo name normalized.
        Tạo edge (Paper)-[:PUBLISHED_AT]->(Venue) với volume/issue/pages trên edge.
        """
        name_normalized = _normalize_name(venue_name)
        query = """
        MERGE (v:Venue {name: $name_normalized})
        ON CREATE SET
            v.id        = randomUUID(),
            v.type      = $venue_type,
            v.publisher = $publisher
        WITH v
        MATCH (p:Paper {id: $paper_id})
        MERGE (p)-[r:PUBLISHED_AT]->(v)
        ON CREATE SET
            r.volume = $volume,
            r.issue  = $issue,
            r.pages  = $pages
        ON MATCH SET
            r.volume = $volume,
            r.issue  = $issue,
            r.pages  = $pages
        """
        self.execute_write(query, {
            "name_normalized": name_normalized,
            "venue_type":      venue_type,
            "publisher":       publisher,
            "paper_id":        paper_id,
            "volume":          volume,
            "issue":           issue,
            "pages":           pages,
        })

    # ------------------------------------------------------------------
    # SECTION 6 MERGE TEMPLATES — Giai đoạn 2
    # ------------------------------------------------------------------

    # ── Topic ───────────────────────────────────────────────────────────

    def merge_topics(
        self,
        *,
        paper_id: str,
        topics: list[str],
        source: str = "keyword",
    ) -> None:
        """
        Batch MERGE Topic từ keywords list.
        source: "keyword" | "llm_extracted"

        Verify paper tồn tại trước khi UNWIND batch để tránh silent fail.
        """
        normalized = [t.lower().strip() for t in topics if t.strip()]
        if not normalized:
            return

        if not self.get_paper_by_id(paper_id):
            raise Neo4jMergeError(
                f"merge_topics: paper_id '{paper_id}' không tìm thấy. "
                "Đảm bảo merge_paper() đã chạy trước."
            )

        query = """
        UNWIND $topics AS topic_name
        MERGE (t:Topic {name: topic_name})
        ON CREATE SET t.id = randomUUID()
        WITH t, topic_name
        MATCH (p:Paper {id: $paper_id})
        MERGE (p)-[r:HAS_TOPIC]->(t)
        ON CREATE SET r.source = $source
        ON MATCH SET  r.source = $source
        """
        self.execute_write(query, {
            "topics":   normalized,
            "paper_id": paper_id,
            "source":   source,
        })

    # ── Method ──────────────────────────────────────────────────────────

    def merge_method(
        self,
        *,
        paper_id: str,
        method_name: str,
        category: Optional[str] = None,
        aliases: list[str] | None = None,
        source_section: str = "method",
        confidence: float = 1.0,
        evidence: str = "",
    ) -> None:
        """
        MERGE Method + edge (Paper)-[:USES_METHOD]->(Method).
        aliases được lưu dạng string "alias1|alias2" (không phải list).
        ON MATCH SET giữ confidence cao nhất khi pipeline chạy lại.  [fix-2]
        """
        name_canonical = method_name.lower().strip()
        aliases_text = "|".join(a.lower().strip() for a in (aliases or []))
        query = """
        MERGE (m:Method {name: $method_name})
        ON CREATE SET
            m.id           = randomUUID(),
            m.category     = $category,
            m.aliases_text = $aliases_text
        WITH m
        MATCH (p:Paper {id: $paper_id})
        MERGE (p)-[r:USES_METHOD]->(m)
        ON CREATE SET
            r.source_section = $source_section,
            r.confidence     = $confidence,
            r.evidence       = $evidence
        ON MATCH SET
            r.confidence = CASE WHEN $confidence > r.confidence
                           THEN $confidence ELSE r.confidence END,
            r.evidence   = CASE WHEN $confidence > r.confidence
                           THEN $evidence ELSE r.evidence END
        """
        self.execute_write(query, {
            "method_name":    name_canonical,
            "category":       category,
            "aliases_text":   aliases_text,
            "paper_id":       paper_id,
            "source_section": source_section,
            "confidence":     confidence,
            "evidence":       evidence[:200],
        })

    def lookup_method_by_fulltext(
        self,
        name: str,
        threshold: float = 0.75,
    ) -> Optional[str]:
        """
        Full-text search Method node theo name và aliases_text.  [fix-5]
        Trả về name canonical của node nếu tìm thấy, None nếu không.

        Dùng bởi EntityMerger trong graph_updater.py để detect duplicate
        trước khi gọi apoc.refactor.mergeNodes.

        Schema note: dùng index method_ft trên (name, aliases_text).
        Trả về name (không phải id) vì MERGE_METHOD_CYPHER trong graph_updater
        dùng MATCH (m:Method {name: $name}).
        """
        query = """
        CALL db.index.fulltext.queryNodes('method_ft', $query_str)
        YIELD node, score
        WHERE score >= $threshold
        RETURN node.name AS name, score
        ORDER BY score DESC
        LIMIT 1
        """
        results = self.execute_read(query, {
            "query_str": name.strip(),
            "threshold": threshold,
        })
        if results:
            logger.debug(
                "lookup_method_by_fulltext: found '%s' score=%.2f",
                results[0]["name"], results[0]["score"],
            )
            return results[0]["name"]
        return None

    # ── Dataset ─────────────────────────────────────────────────────────

    def merge_dataset(
        self,
        *,
        paper_id: str,
        dataset_name: str,
        dataset_language: Optional[str] = None,
        aliases: list[str] | None = None,
        source_section: str = "experiment",
        confidence: float = 1.0,
        evidence: str = "",
        metric: Optional[str] = None,
    ) -> None:
        """
        MERGE Dataset + edge (Paper)-[:EVALUATES_ON]->(Dataset).
        ON MATCH SET giữ confidence cao nhất khi pipeline chạy lại.  [fix-2]
        """
        name_canonical = dataset_name.lower().strip()
        aliases_text = "|".join(a.lower().strip() for a in (aliases or []))
        query = """
        MERGE (d:Dataset {name: $dataset_name})
        ON CREATE SET
            d.id           = randomUUID(),
            d.language     = $dataset_language,
            d.aliases_text = $aliases_text
        WITH d
        MATCH (p:Paper {id: $paper_id})
        MERGE (p)-[r:EVALUATES_ON]->(d)
        ON CREATE SET
            r.source_section = $source_section,
            r.confidence     = $confidence,
            r.evidence       = $evidence,
            r.metric         = $metric
        ON MATCH SET
            r.confidence = CASE WHEN $confidence > r.confidence
                           THEN $confidence ELSE r.confidence END,
            r.evidence   = CASE WHEN $confidence > r.confidence
                           THEN $evidence ELSE r.evidence END
        """
        self.execute_write(query, {
            "dataset_name":     name_canonical,
            "dataset_language": dataset_language,
            "aliases_text":     aliases_text,
            "paper_id":         paper_id,
            "source_section":   source_section,
            "confidence":       confidence,
            "evidence":         evidence[:200],
            "metric":           metric,
        })

    def lookup_dataset_by_fulltext(
        self,
        name: str,
        threshold: float = 0.75,
    ) -> Optional[str]:
        """
        Full-text search Dataset node theo name và aliases_text.  [fix-5]
        Trả về name canonical của node nếu tìm thấy, None nếu không.

        Tương tự lookup_method_by_fulltext — xem docstring đó để biết thêm.
        Schema note: dùng index dataset_ft trên (name, aliases_text).
        """
        query = """
        CALL db.index.fulltext.queryNodes('dataset_ft', $query_str)
        YIELD node, score
        WHERE score >= $threshold
        RETURN node.name AS name, score
        ORDER BY score DESC
        LIMIT 1
        """
        results = self.execute_read(query, {
            "query_str": name.strip(),
            "threshold": threshold,
        })
        if results:
            logger.debug(
                "lookup_dataset_by_fulltext: found '%s' score=%.2f",
                results[0]["name"], results[0]["score"],
            )
            return results[0]["name"]
        return None

    # ── Task ────────────────────────────────────────────────────────────

    def merge_task(
        self,
        *,
        paper_id: str,
        task_name: str,
        source_section: str = "abstract",
        confidence: float = 1.0,
        evidence: str = "",
    ) -> None:
        """
        MERGE Task + edge (Paper)-[:ADDRESSES_TASK]->(Task).
        ON MATCH SET giữ confidence cao nhất khi pipeline chạy lại.  [fix-2]
        """
        name_canonical = task_name.lower().strip()
        query = """
        MERGE (tk:Task {name: $task_name})
        ON CREATE SET tk.id = randomUUID()
        WITH tk
        MATCH (p:Paper {id: $paper_id})
        MERGE (p)-[r:ADDRESSES_TASK]->(tk)
        ON CREATE SET
            r.source_section = $source_section,
            r.confidence     = $confidence,
            r.evidence       = $evidence
        ON MATCH SET
            r.confidence = CASE WHEN $confidence > r.confidence
                           THEN $confidence ELSE r.confidence END,
            r.evidence   = CASE WHEN $confidence > r.confidence
                           THEN $evidence ELSE r.evidence END
        """
        self.execute_write(query, {
            "task_name":      name_canonical,
            "paper_id":       paper_id,
            "source_section": source_section,
            "confidence":     confidence,
            "evidence":       evidence[:200],
        })

    # ── Method BASED_ON ─────────────────────────────────────────────────

    def merge_method_based_on(
        self,
        *,
        child_method: str,
        parent_method: str,
        confidence: float = 1.0,
    ) -> None:
        """
        (Method)-[:BASED_ON]->(Method)
        VD: phobert → bert
        Cả 2 method phải tồn tại trước khi gọi hàm này.
        """
        query = """
        MATCH (m1:Method {name: $child})
        MATCH (m2:Method {name: $parent})
        MERGE (m1)-[r:BASED_ON]->(m2)
        ON CREATE SET r.confidence = $confidence
        RETURN m1.name AS child_found, m2.name AS parent_found
        """
        result = self.execute_write(query, {
            "child":      child_method.lower().strip(),
            "parent":     parent_method.lower().strip(),
            "confidence": confidence,
        })
        if not result:
            logger.error(
                "merge_method_based_on: '%s' hoặc '%s' không tồn tại trong graph. "
                "Gọi merge_method() cho cả 2 trước khi tạo BASED_ON edge.",
                child_method, parent_method,
            )
            raise Neo4jMergeError(
                f"merge_method_based_on: method '{child_method}' hoặc "
                f"'{parent_method}' không tìm thấy"
            )

    # ------------------------------------------------------------------
    # SECTION 6 MERGE TEMPLATES — Giai đoạn 3
    # ------------------------------------------------------------------

    # ── Citation edge ───────────────────────────────────────────────────

    def merge_citation(
        self,
        *,
        citing_paper_id: str,
        cited_doi: Optional[str] = None,
        cited_title: Optional[str] = None,
        cited_year: Optional[int] = None,
        raw_ref_text: str = "",
    ) -> None:
        """
        Tạo edge (Paper)-[:CITES]->(Paper).
        Confidence:
            1.0 = doi match
            0.8 = title + year exact
            0.6 = title only, year = null

        CẢNH BÁO [fix-3]: khi cited_year=None, 2 paper khác nhau cùng title
        sẽ bị merge thành 1 node. graph_builder._merge_citation() nên check
        len(cited_title) >= 10 trước khi gọi hàm này.
        """
        if cited_doi:
            confidence = 1.0
            query = """
            MATCH (p1:Paper {id: $citing_id})
            MERGE (p2:Paper {doi: $cited_doi})
            ON CREATE SET
                p2.id                = randomUUID(),
                p2.title             = $cited_title,
                p2.year              = $cited_year,
                p2.processing_status = 'stub',
                p2.created_at        = datetime()
            MERGE (p1)-[r:CITES]->(p2)
            ON CREATE SET
                r.confidence   = $confidence,
                r.raw_ref_text = $raw_ref_text
            """
            self.execute_write(query, {
                "citing_id":    citing_paper_id,
                "cited_doi":    cited_doi,
                "cited_title":  cited_title or "",
                "cited_year":   cited_year,
                "confidence":   confidence,
                "raw_ref_text": raw_ref_text[:500],
            })

        elif cited_title:
            confidence = 0.8 if cited_year else 0.6
            query = """
            MATCH (p1:Paper {id: $citing_id})
            MERGE (p2:Paper {title: $cited_title, year: $cited_year})
            ON CREATE SET
                p2.id                = randomUUID(),
                p2.processing_status = 'stub',
                p2.created_at        = datetime()
            ON MATCH SET
                p2.processing_status = CASE
                    WHEN p2.processing_status = 'stub' THEN 'stub'
                    ELSE p2.processing_status
                END
            MERGE (p1)-[r:CITES]->(p2)
            ON CREATE SET
                r.confidence   = $confidence,
                r.raw_ref_text = $raw_ref_text
            """
            self.execute_write(query, {
                "citing_id":    citing_paper_id,
                "cited_title":  cited_title,
                "cited_year":   cited_year,
                "confidence":   confidence,
                "raw_ref_text": raw_ref_text[:500],
            })
        else:
            logger.warning(
                "merge_citation: citing=%s — cited paper không có doi lẫn title, bỏ qua",
                citing_paper_id,
            )

    # ------------------------------------------------------------------
    # SIMILAR_TO edge — offline recommendation
    # ------------------------------------------------------------------

    def merge_similar_to(
        self,
        *,
        paper_id_1: str,
        paper_id_2: str,
        score: float,
        shared_methods: list[str] | None = None,
        shared_authors: list[str] | None = None,
    ) -> None:
        """
        (Paper)-[:SIMILAR_TO {score, shared_methods, shared_authors}]->(Paper)
        Chỉ insert khi score >= threshold (threshold do caller quyết định).
        shared_methods / shared_authors lưu dạng string "a|b|c".

        NOTE: SIMILAR_TO cần được thêm vào neo4j_schema.cypher Section 5
        và thêm index trên r.score nếu query theo score thường xuyên.
        """
        query = """
        MATCH (p1:Paper {id: $id1})
        MATCH (p2:Paper {id: $id2})
        MERGE (p1)-[r:SIMILAR_TO]->(p2)
        ON CREATE SET
            r.score          = $score,
            r.shared_methods = $shared_methods,
            r.shared_authors = $shared_authors
        ON MATCH SET
            r.score          = $score
        RETURN p1.id AS p1_found, p2.id AS p2_found
        """
        result = self.execute_write(query, {
            "id1":            paper_id_1,
            "id2":            paper_id_2,
            "score":          round(score, 4),
            "shared_methods": "|".join(shared_methods or []),
            "shared_authors": "|".join(shared_authors or []),
        })
        if not result:
            logger.error(
                "merge_similar_to: paper_id_1='%s' hoặc paper_id_2='%s' không tồn tại.",
                paper_id_1, paper_id_2,
            )
            raise Neo4jMergeError(
                f"merge_similar_to: '{paper_id_1}' hoặc '{paper_id_2}' không tìm thấy"
            )

    # ------------------------------------------------------------------
    # Chunk node — Giai đoạn 3
    # ------------------------------------------------------------------

    def merge_chunk(
        self,
        *,
        paper_id: str,
        qdrant_id: str,
        section: str = "",
        page: Optional[int] = None,
        chunk_text: str = "",
    ) -> None:
        """
        MERGE Chunk node + edge (Paper)-[:HAS_CHUNK]->(Chunk).
        qdrant_id là ID đã lưu trong Qdrant (lấy từ qdrant_client sau khi upsert).
        Neo4j chỉ lưu preview 1000 chars để debug; full text nằm ở Qdrant.
        """
        _CHUNK_TEXT_LIMIT = 1000
        truncated_text = chunk_text
        if len(chunk_text) > _CHUNK_TEXT_LIMIT:
            logger.warning(
                "merge_chunk: qdrant_id='%s' chunk_text bị truncate từ %d → %d chars. "
                "Full text xem tại Qdrant.",
                qdrant_id, len(chunk_text), _CHUNK_TEXT_LIMIT,
            )
            truncated_text = chunk_text[:_CHUNK_TEXT_LIMIT]

        query = """
        MERGE (c:Chunk {qdrant_id: $qdrant_id})
        ON CREATE SET
            c.id      = randomUUID(),
            c.section = $section,
            c.page    = $page,
            c.text    = $chunk_text
        WITH c
        MATCH (p:Paper {id: $paper_id})
        MERGE (p)-[:HAS_CHUNK]->(c)
        RETURN p.id AS paper_found
        """
        result = self.execute_write(query, {
            "qdrant_id":  qdrant_id,
            "section":    section,
            "page":       page,
            "chunk_text": truncated_text,
            "paper_id":   paper_id,
        })
        if not result:
            logger.error(
                "merge_chunk: paper_id='%s' không tồn tại. "
                "Chunk qdrant_id='%s' không được link vào graph.",
                paper_id, qdrant_id,
            )
            raise Neo4jMergeError(f"merge_chunk: paper_id '{paper_id}' không tìm thấy")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def set_paper_status(self, paper_id: str, status: str) -> None:
        """
        status: "stub" | "parsed" | "kg_built" | "embedded"
        Gọi sau khi hoàn thành từng giai đoạn của pipeline.
        """
        valid = {"stub", "parsed", "kg_built", "embedded"}
        if status not in valid:
            raise ValueError(f"set_paper_status: status không hợp lệ '{status}'. Phải là {valid}")
        query = "MATCH (p:Paper {id: $id}) SET p.processing_status = $status"
        self.execute_write(query, {"id": paper_id, "status": status})

    def get_paper_by_id(self, paper_id: str) -> Optional[dict]:
        query = "MATCH (p:Paper {id: $id}) RETURN p"
        rows = self.execute_read(query, {"id": paper_id})
        return dict(rows[0]["p"]) if rows else None

    def get_papers_by_status(self, status: str) -> list[dict]:
        query = "MATCH (p:Paper {processing_status: $status}) RETURN p"
        rows = self.execute_read(query, {"status": status})
        return [dict(r["p"]) for r in rows]

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        try:
            self.execute_read("RETURN 1 AS ok")
            return True
        except (ServiceUnavailable, TransientError) as e:
            logger.error("Neo4j ping failed: %s", e)
            return False
