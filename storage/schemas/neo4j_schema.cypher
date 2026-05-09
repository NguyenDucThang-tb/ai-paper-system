// =============================================================================
// NEO4J SCHEMA — Paper RAG + Knowledge Graph System
// Target:  Neo4j 5.x
// Updated: sửa author uniqueness, thêm Institution node,
//          bỏ index list property, fix full-text index aliases,
//          fix NODE KEY bug, thêm ON MATCH SET cho confidence edges
// =============================================================================
// Thứ tự chạy bắt buộc:
//   1. Constraints  → phải có trước bất kỳ MERGE nào
//   2. Indexes      → tối ưu query
//   3. Full-text    → fuzzy search author/title/method
// Chạy từng block, kiểm tra lỗi trước khi chạy block tiếp theo.
// =============================================================================


// =============================================================================
// SECTION 1 — CONSTRAINTS
// Chia theo 3 giai đoạn build để dễ rollout dần.
// =============================================================================

// -----------------------------------------------------------------------------
// Giai đoạn 1 — MVP: Paper + Author + Institution
// Chạy ngay từ đầu, trước khi ingest bất kỳ paper nào.
// -----------------------------------------------------------------------------

// Paper — id là UUID sinh trong pipeline, luôn có
CREATE CONSTRAINT paper_id IF NOT EXISTS
  FOR (p:Paper) REQUIRE p.id IS UNIQUE;

// Paper — doi là preferred unique key khi có
// Neo4j 5.x: UNIQUE constraint cho phép nhiều node doi = null — behavior đúng
// Neo4j 4.x: KHÔNG cho phép nhiều null — cần test kỹ nếu dùng 4.x
// Constraint này tự động tạo index trên doi — KHÔNG tạo thêm index thủ công
CREATE CONSTRAINT paper_doi IF NOT EXISTS
  FOR (p:Paper) REQUIRE p.doi IS UNIQUE;

// Paper — fallback key khi không có doi
// Bắt buộc normalize title trước khi MERGE:
//   lowercase → strip → collapse whitespace → remove special chars
// Nếu không normalize, cùng một paper sẽ tạo 2 node khác nhau.
//
// KHÔNG dùng NODE KEY vì year có thể null (paper không rõ năm).
// NODE KEY bắt buộc cả 2 field NOT NULL → insert fail nếu year = null.
// Dùng composite index thường thay thế; uniqueness được enforce ở tầng Python
// trong graph_builder.py trước khi gọi MERGE.
CREATE INDEX paper_title_year IF NOT EXISTS
  FOR (p:Paper) ON (p.title, p.year);
//
// Quy tắc xử lý year = null trong graph_builder.py:
//   1. Thử parse year từ nội dung file (regex trên header/footer).
//   2. Thử lấy từ reference section của paper khác cite đến paper này.
//   3. Nếu vẫn null → set year = 0 (sentinel) để tránh collision, ghi log warning.
//   Không dùng -1 vì Neo4j sort int, 0 ít gây nhầm lẫn hơn.

// Author — unique theo id (UUID), KHÔNG unique theo name vì trùng tên phổ biến.
// MERGE logic trong graph_builder.py:
//   1. Lookup bằng (name, affiliation) qua full-text index
//   2. Nếu score >= threshold → MATCH node đó
//   3. Nếu không tìm thấy    → CREATE với id mới
CREATE CONSTRAINT author_id IF NOT EXISTS
  FOR (a:Author) REQUIRE a.id IS UNIQUE;

// Institution — tên tổ chức là unique key (sau normalize)
// Normalize: lowercase, bỏ dấu, collapse whitespace
// VD: "Đại học Quốc gia Hà Nội" → "dai hoc quoc gia ha noi"
CREATE CONSTRAINT institution_name IF NOT EXISTS
  FOR (i:Institution) REQUIRE i.name IS UNIQUE;

// -----------------------------------------------------------------------------
// Giai đoạn 2 — Method, Dataset, Task, Topic
// Chạy sau khi giai đoạn 1 ổn định và LLM extraction đã sẵn sàng.
// -----------------------------------------------------------------------------

// Method — unique theo name canonical (đã normalize + lowercase)
// graph_builder.py cần check aliases_text trước khi tạo node mới
CREATE CONSTRAINT method_name IF NOT EXISTS
  FOR (m:Method) REQUIRE m.name IS UNIQUE;

// Dataset — unique theo name (đã normalize)
CREATE CONSTRAINT dataset_name IF NOT EXISTS
  FOR (d:Dataset) REQUIRE d.name IS UNIQUE;

// Task — unique theo name lowercase canonical
// VD: "named entity recognition", "sentiment analysis"
CREATE CONSTRAINT task_name IF NOT EXISTS
  FOR (tk:Task) REQUIRE tk.name IS UNIQUE;

// Topic — đến từ UnifiedDocument.keywords (đã lowercase khi MERGE)
CREATE CONSTRAINT topic_name IF NOT EXISTS
  FOR (t:Topic) REQUIRE t.name IS UNIQUE;

// Venue — tên journal/conference sau normalize
CREATE CONSTRAINT venue_name IF NOT EXISTS
  FOR (v:Venue) REQUIRE v.name IS UNIQUE;

// -----------------------------------------------------------------------------
// Giai đoạn 3 — Citation graph
// Không cần constraint mới. Citation chỉ tạo thêm edge [:CITES]
// giữa các Paper đã có, hoặc tạo stub Paper dùng paper_id constraint.
// -----------------------------------------------------------------------------


// =============================================================================
// SECTION 2 — PROPERTY INDEXES
// Chỉ tạo cho field thường xuyên filter/sort.
// Không tạo index cho list property (chunk_ids) — Neo4j không query list hiệu quả.
// =============================================================================

// Paper — filter theo năm và ngôn ngữ (dùng nhiều trong recommendation query)
CREATE INDEX paper_year     IF NOT EXISTS FOR (p:Paper) ON (p.year);
CREATE INDEX paper_language IF NOT EXISTS FOR (p:Paper) ON (p.language);

// Paper — track trạng thái pipeline (tìm stub paper cần ingest, paper chưa embed)
CREATE INDEX paper_status IF NOT EXISTS FOR (p:Paper) ON (p.processing_status);

// Author — group theo affiliation raw (trước khi link sang Institution)
CREATE INDEX author_affiliation IF NOT EXISTS FOR (a:Author) ON (a.affiliation);

// Institution — filter theo quốc gia
CREATE INDEX institution_country IF NOT EXISTS FOR (i:Institution) ON (i.country);

// Method — filter theo category ("tìm paper dùng pretrained_lm")
CREATE INDEX method_category IF NOT EXISTS FOR (m:Method) ON (m.category);

// Dataset — filter theo ngôn ngữ dataset
CREATE INDEX dataset_language IF NOT EXISTS FOR (d:Dataset) ON (d.language);


// =============================================================================
// SECTION 3 — FULL-TEXT INDEXES
// Dùng cho fuzzy lookup trong graph_builder.py và entity_extractor.py.
// Quan trọng: chỉ hoạt động trên STRING property, không phải list.
// aliases được lưu dạng "alias1|alias2|alias3" thay vì list[str].
// =============================================================================

// Author — tìm gần đúng theo name và name_ascii (bỏ dấu tiếng Việt)
CREATE FULLTEXT INDEX author_ft IF NOT EXISTS
  FOR (a:Author) ON EACH [a.name, a.name_ascii];

// Paper — tìm gần đúng theo title (khi Reference chỉ có title, không có doi)
CREATE FULLTEXT INDEX paper_title_ft IF NOT EXISTS
  FOR (p:Paper) ON EACH [p.title];

// Method — tìm theo name và aliases_text ("bert|bert-base|bert-base-uncased")
CREATE FULLTEXT INDEX method_ft IF NOT EXISTS
  FOR (m:Method) ON EACH [m.name, m.aliases_text];

// Dataset — tìm theo name và aliases_text
CREATE FULLTEXT INDEX dataset_ft IF NOT EXISTS
  FOR (d:Dataset) ON EACH [d.name, d.aliases_text];

// Institution — tìm gần đúng tên trường Việt Nam (nhiều cách viết khác nhau)
CREATE FULLTEXT INDEX institution_ft IF NOT EXISTS
  FOR (i:Institution) ON EACH [i.name, i.name_ascii];


// =============================================================================
// SECTION 4 — NODE PROPERTY REFERENCE
// graph_builder.py phải tuân theo spec này khi SET property.
// Field có dấu ? là optional, có thể null.
// =============================================================================

// --- :Paper ---
// {
//   id:                string   — UUID, sinh bởi pipeline, luôn có
//   title:             string   — required, đã normalize
//   year:              int?     — required nếu không có doi; dùng 0 làm sentinel
//   doi:               string?  — preferred unique key, null nếu không có
//   abstract:          string?  — lưu để embed sang Qdrant
//   language:          string   — "vi" | "en" | "bilingual"
//   source_file:       string   — đường dẫn file gốc
//   source_type:       string   — "pdf" | "docx" | "html"
//   page_count:        int?
//   citation_count:    int?     — từ Semantic Scholar / CrossRef nếu có
//   chunk_ids:         list     — ID chunks trong Qdrant (không index, chỉ lưu)
//   processing_status: string   — "stub" | "parsed" | "kg_built" | "embedded"
//   created_at:        datetime
// }

// --- :Author ---
// {
//   id:          string   — UUID (primary key)
//   name:        string   — tên gốc, giữ nguyên dấu
//   name_ascii:  string?  — bỏ dấu tiếng Việt, dùng cho full-text index
//   email:       string?  — từ Regex extraction (UnifiedDocument)
//   affiliation: string?  — tên tổ chức raw, trước khi link sang Institution
// }
// Lưu ý: KHÔNG có name UNIQUE.
// "Nguyễn Văn A" ở ĐHQGHN và "Nguyễn Văn A" ở ĐHBK là 2 Author node khác nhau.

// --- :Institution ---
// {
//   id:           string   — UUID
//   name:         string   — normalized unique key (lowercase + bỏ dấu + collapse ws)
//                            đây là field dùng để MERGE, không phải để hiển thị
//   display_name: string?  — tên gốc giữ nguyên dấu, dùng để hiển thị trên UI
//   name_ascii:   string?  — bỏ dấu, dùng cho full-text index
//   country:      string?  — "VN" | "US" | ...
//   type:         string?  — "university" | "institute" | "company" | "other"
// }

// --- :Venue ---
// {
//   id:        string
//   name:      string   — tên journal/conference (normalize, unique key)
//   type:      string   — "journal" | "conference" | "workshop" | "preprint"
//   publisher: string?
// }

// --- :Topic ---
// {
//   id:   string
//   name: string   — lowercase, đã strip dấu câu (unique key)
// }

// --- :Method ---
// {
//   id:           string
//   name:         string   — tên canonical lowercase (unique key)
//   category:     string?  — "pretrained_lm" | "sequence_labeling" |
//                            "generative" | "classical" | "other"
//   aliases_text: string?  — "alias1|alias2|alias3" — STRING, không phải list
// }

// --- :Dataset ---
// {
//   id:           string
//   name:         string   — tên canonical (unique key)
//   language:     string?  — "vi" | "en" | "multilingual"
//   size:         string?  — VD: "10000 samples"
//   aliases_text: string?  — "alias1|alias2" — STRING, không phải list
// }

// --- :Task ---
// {
//   id:   string
//   name: string   — lowercase canonical (unique key)
//                    VD: "named entity recognition", "sentiment analysis"
// }


// =============================================================================
// SECTION 5 — RELATIONSHIP SCHEMA
// Thứ tự = thứ tự build trong graph_builder.py.
// Property trên edge là provenance + confidence — không enforce bởi Neo4j,
// graph_builder.py phải tự validate trước khi SET.
// =============================================================================

// --- Giai đoạn 1 ---

// (Author)-[:WROTE {order: int}]->(Paper)
//   order: 0 = first author, 1 = second author, ...

// (Author)-[:AFFILIATED_WITH]->(Institution)
//   Institution != Venue.
//   Institution = nơi tác giả làm việc (trường, viện, công ty).
//   Venue       = nơi paper được đăng (journal, conference).

// (Paper)-[:PUBLISHED_AT {volume, issue, pages}]->(Venue)

// --- Giai đoạn 2 ---

// (Paper)-[:HAS_TOPIC {source: "keyword" | "llm_extracted"}]->(Topic)

// (Paper)-[:USES_METHOD {source_section, confidence, evidence}]->(Method)
//   source_section: "abstract" | "method" | "experiment" | "conclusion"
//   confidence:     float 0.0 → 1.0, từ LLM output
//   evidence:       string <= 200 chars, câu văn gốc làm bằng chứng

// (Paper)-[:EVALUATES_ON {source_section, confidence, evidence, metric}]->(Dataset)
//   metric: string? — VD: "F1=92.3" nếu extract được từ table/text

// (Paper)-[:ADDRESSES_TASK {source_section, confidence, evidence}]->(Task)

// (Method)-[:BASED_ON {confidence}]->(Method)
//   VD: (:Method {name:"phobert"})-[:BASED_ON]->(:Method {name:"bert"})

// --- Giai đoạn 3 ---

// (Paper)-[:CITES {confidence, raw_ref_text}]->(Paper)
//   confidence:   1.0 = doi match
//                 0.8 = (title + year) exact match
//                 0.6 = fuzzy title match
//   raw_ref_text: text citation gốc, dùng để debug khi cần


// =============================================================================
// SECTION 6 — MERGE TEMPLATES
// Copy sang graph_builder.py, thay $param bằng giá trị thực.
// Tất cả dùng MERGE để idempotent — chạy lại pipeline không tạo duplicate.
// =============================================================================

// -- Paper: MERGE strategy --
// CẢNH BÁO: KHÔNG BAO GIỜ làm MERGE (p:Paper {doi: null}).
// Neo4j sẽ match tất cả paper không có doi thành 1 node duy nhất.
// Phải dùng if/else trong Python trước khi gọi Cypher:
//
//   if doc.doi:
//       _merge_paper_by_doi(doc)
//   else:
//       _merge_paper_by_title_year(doc)

// -- Paper (có doi) --
// MERGE (p:Paper {doi: $doi})
// ON CREATE SET
//   p.id                = $id,
//   p.title             = $title,
//   p.year              = $year,
//   p.abstract          = $abstract,
//   p.language          = $language,
//   p.source_file       = $source_file,
//   p.source_type       = $source_type,
//   p.citation_count    = $citation_count,
//   p.chunk_ids         = $chunk_ids,
//   p.processing_status = 'parsed',
//   p.created_at        = datetime()
// ON MATCH SET
//   p.chunk_ids         = $chunk_ids,
//   p.processing_status = 'parsed';

// -- Paper (fallback: doi = null, dùng title + year) --
// Đảm bảo $year != null trước khi gọi — dùng 0 làm sentinel nếu không rõ năm.
// MERGE (p:Paper {title: $title, year: $year})
// ON CREATE SET
//   p.id                = $id,
//   p.language          = $language,
//   p.source_file       = $source_file,
//   p.source_type       = $source_type,
//   p.chunk_ids         = $chunk_ids,
//   p.processing_status = 'parsed',
//   p.created_at        = datetime()
// ON MATCH SET
//   p.chunk_ids         = $chunk_ids;

// -- Citation stub (paper chưa ingest, giữ edge trước) --
// MERGE (p:Paper {doi: $cited_doi})
// ON CREATE SET
//   p.id                = randomUUID(),
//   p.title             = $cited_title,
//   p.year              = $cited_year,
//   p.processing_status = 'stub',
//   p.created_at        = datetime();

// -- Author (dùng id làm MERGE key) --
// MERGE (a:Author {id: $author_id})
// ON CREATE SET
//   a.name        = $name,
//   a.name_ascii  = $name_ascii,
//   a.email       = $email,
//   a.affiliation = $affiliation
// WITH a
// MATCH (p:Paper {id: $paper_id})
// MERGE (a)-[:WROTE {order: $order}]->(p);

// -- Institution + edge AFFILIATED_WITH --
// $inst_name_normalized = lowercase + bỏ dấu (dùng để MERGE)
// $inst_display_name    = tên gốc giữ nguyên dấu (dùng để hiển thị)
// MERGE (i:Institution {name: $inst_name_normalized})
// ON CREATE SET
//   i.id           = randomUUID(),
//   i.display_name = $inst_display_name,
//   i.name_ascii   = $inst_name_ascii,
//   i.country      = $country,
//   i.type         = $inst_type
// WITH i
// MATCH (a:Author {id: $author_id})
// MERGE (a)-[:AFFILIATED_WITH]->(i);

// -- Venue + edge PUBLISHED_AT --
// MERGE (v:Venue {name: $venue_name_normalized})
// ON CREATE SET
//   v.id        = randomUUID(),
//   v.type      = $venue_type,
//   v.publisher = $publisher
// WITH v
// MATCH (p:Paper {id: $paper_id})
// MERGE (p)-[:PUBLISHED_AT {volume: $volume, issue: $issue, pages: $pages}]->(v);

// -- Topic batch (từ keywords list) --
// UNWIND $topics AS topic_name
// MERGE (t:Topic {name: topic_name})
// ON CREATE SET t.id = randomUUID()
// WITH t, topic_name
// MATCH (p:Paper {id: $paper_id})
// MERGE (p)-[:HAS_TOPIC {source: $source}]->(t);

// -- Method + edge USES_METHOD (từ LLM extraction) --
// MERGE (m:Method {name: $method_name})
// ON CREATE SET
//   m.id           = randomUUID(),
//   m.category     = $category,
//   m.aliases_text = $aliases_text
// WITH m
// MATCH (p:Paper {id: $paper_id})
// MERGE (p)-[r:USES_METHOD]->(m)
// ON CREATE SET
//   r.source_section = $source_section,
//   r.confidence     = $confidence,
//   r.evidence       = $evidence
// ON MATCH SET
//   r.confidence = CASE WHEN $confidence > r.confidence
//                  THEN $confidence ELSE r.confidence END,
//   r.evidence   = CASE WHEN $confidence > r.confidence
//                  THEN $evidence ELSE r.evidence END;

// -- Dataset + edge EVALUATES_ON --
// MERGE (d:Dataset {name: $dataset_name})
// ON CREATE SET
//   d.id           = randomUUID(),
//   d.language     = $dataset_language,
//   d.aliases_text = $aliases_text
// WITH d
// MATCH (p:Paper {id: $paper_id})
// MERGE (p)-[r:EVALUATES_ON]->(d)
// ON CREATE SET
//   r.source_section = $source_section,
//   r.confidence     = $confidence,
//   r.evidence       = $evidence,
//   r.metric         = $metric
// ON MATCH SET
//   r.confidence = CASE WHEN $confidence > r.confidence
//                  THEN $confidence ELSE r.confidence END,
//   r.evidence   = CASE WHEN $confidence > r.confidence
//                  THEN $evidence ELSE r.evidence END;

// -- Task + edge ADDRESSES_TASK --
// MERGE (tk:Task {name: $task_name})
// ON CREATE SET tk.id = randomUUID()
// WITH tk
// MATCH (p:Paper {id: $paper_id})
// MERGE (p)-[r:ADDRESSES_TASK]->(tk)
// ON CREATE SET
//   r.source_section = $source_section,
//   r.confidence     = $confidence,
//   r.evidence       = $evidence
// ON MATCH SET
//   r.confidence = CASE WHEN $confidence > r.confidence
//                  THEN $confidence ELSE r.confidence END,
//   r.evidence   = CASE WHEN $confidence > r.confidence
//                  THEN $evidence ELSE r.evidence END;

// -- Citation edge --
// MATCH (p1:Paper {id: $citing_paper_id})
// MATCH (p2:Paper {doi: $cited_doi})
// MERGE (p1)-[r:CITES]->(p2)
// ON CREATE SET
//   r.confidence   = $confidence,
//   r.raw_ref_text = $raw_ref_text;

// -- Method BASED_ON --
// MATCH (m1:Method {name: $child_method})
// MATCH (m2:Method {name: $parent_method})
// MERGE (m1)-[r:BASED_ON]->(m2)
// ON CREATE SET r.confidence = $confidence;
