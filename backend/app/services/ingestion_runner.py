from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import traceback

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.document_artifact import DocumentArtifact
from app.models.document_job import DocumentJob
from app.models.document_metadata import DocumentMetadata
from app.models.document_graph import DocumentGraph

logger = logging.getLogger(__name__)


def _strip_nul(text: str | None) -> str:
    if not text:
        return ""
    return str(text).replace("\x00", "")


def _sanitize_payload_strings(obj):
    if isinstance(obj, str):
        return _strip_nul(obj)
    if isinstance(obj, list):
        return [_sanitize_payload_strings(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _sanitize_payload_strings(value) for key, value in obj.items()}
    return obj

def _detect_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "ingestion").exists() and (parent / "ai_module").exists():
            return parent
    # Fallback for container layout where app code lives under /app/app/*
    return current.parents[2]


PROJECT_ROOT = _detect_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.pipeline import run_pipeline  # noqa: E402
from app.services.file_extractor import (  # noqa: E402
    extract_text_from_docx,
    extract_text_from_pdf,
    extract_text_from_txt,
)


def _serialize_doc_for_json(doc_obj) -> dict:
    if isinstance(doc_obj, dict):
        payload = dict(doc_obj)
    else:
        payload = asdict(doc_obj)
    payload = _sanitize_payload_strings(payload)
    created_at = payload.get("created_at")
    if isinstance(created_at, datetime):
        payload["created_at"] = created_at.isoformat()
    return payload


def _save_processed_json(document: Document, doc_obj) -> Path:
    out_dir = PROJECT_ROOT / "data" / "processed" / str(document.user_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(document.filename).stem
    out_path = out_dir / f"{stem}.json"
    out_path.write_text(
        json.dumps(_serialize_doc_for_json(doc_obj), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


_GENERIC_TITLES = {
    "đặt vấn đề",
    "mở đầu",
    "introduction",
    "abstract",
    "kết luận",
    "tài liệu tham khảo",
}


def _is_likely_bad_title(title: str) -> bool:
    t = (title or "").strip().lower()
    if not t:
        return True
    if t in _GENERIC_TITLES:
        return True
    return len(t) < 12


def _is_likely_bad_authors(authors: list[str]) -> bool:
    if not isinstance(authors, list) or not authors:
        return True
    noise_hits = 0
    for a in authors:
        s = str(a or "").strip().lower()
        if not s:
            noise_hits += 1
            continue
        if len(s) > 60 or any(token in s for token in ["điều trị", "nghiên cứu", "phương pháp", "kết quả"]):
            noise_hits += 1
    return noise_hits >= max(1, len(authors) // 2)


def _metadata_quality_score(payload: dict) -> int:
    score = 0
    title = str(payload.get("title") or "").strip()
    authors = payload.get("authors") or []
    abstract = str(payload.get("abstract") or "").strip()
    if title and not _is_likely_bad_title(title):
        score += 4
    if isinstance(authors, list) and authors and not _is_likely_bad_authors(authors):
        score += 4
    if 80 <= len(abstract) <= 2500:
        score += 3
    if payload.get("year"):
        score += 1
    if payload.get("doi"):
        score += 1
    return score


def _repair_metadata_from_existing_json(document: Document, payload: dict) -> dict:
    """
    If current metadata looks low-quality, borrow better metadata
    from existing processed files with same stem across data/processed/*.
    """
    stem = Path(document.filename).stem
    current_score = _metadata_quality_score(payload)
    if current_score >= 8:
        return payload

    base_dir = PROJECT_ROOT / "data" / "processed"
    if not base_dir.exists():
        return payload

    best = payload
    best_score = current_score
    pattern = f"*/{stem}.json"
    for candidate in base_dir.glob(pattern):
        try:
            if candidate.resolve() == (base_dir / str(document.user_id) / f"{stem}.json").resolve():
                continue
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            s = _metadata_quality_score(data)
            if s > best_score:
                best = data
                best_score = s
        except Exception:
            continue

    if best is payload:
        return payload

    repaired = dict(payload)
    for key in ("title", "authors", "abstract", "year", "journal", "doi", "keywords", "language"):
        if best.get(key):
            repaired[key] = best.get(key)
    logger.warning(
        "Metadata repaired from existing JSON for document_id=%s (score %s -> %s)",
        document.id,
        current_score,
        best_score,
    )
    return repaired


def _upsert_metadata(db: Session, document_id: int, doc_obj) -> None:
    meta = (
        db.query(DocumentMetadata)
        .filter(DocumentMetadata.document_id == document_id)
        .first()
    )
    if meta is None:
        meta = DocumentMetadata(document_id=document_id)
        db.add(meta)

    payload = _serialize_doc_for_json(doc_obj)
    meta.title = _strip_nul(payload.get("title"))
    meta.abstract = _strip_nul(payload.get("abstract"))
    meta.publication_year = payload.get("year")
    meta.source = payload.get("journal")
    meta.language = _strip_nul(payload.get("language"))
    meta.authors = [_strip_nul(x) for x in (payload.get("authors") or [])]
    meta.keywords = [_strip_nul(x) for x in (payload.get("keywords") or [])]
    meta.doi = _strip_nul(payload.get("doi"))
    meta.updated_at = datetime.utcnow()


def _upsert_artifact(db: Session, document_id: int, uri: str, size_bytes: int) -> None:
    artifact = (
        db.query(DocumentArtifact)
        .filter(
            DocumentArtifact.document_id == document_id,
            DocumentArtifact.artifact_type == "unified_json",
        )
        .first()
    )
    if artifact is None:
        artifact = DocumentArtifact(
            document_id=document_id,
            artifact_type="unified_json",
            uri=uri,
            size_bytes=size_bytes,
            mime_type="application/json",
        )
        db.add(artifact)
    else:
        artifact.uri = uri
        artifact.size_bytes = size_bytes
        artifact.mime_type = "application/json"


def _artifact_uri_for_db(json_path: Path) -> str:
    try:
        return str(json_path.resolve().relative_to(PROJECT_ROOT).as_posix())
    except Exception:
        return str(json_path.resolve())


def _extract_text_for_fallback(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(str(file_path))
    if suffix == ".docx":
        return extract_text_from_docx(str(file_path))
    return extract_text_from_txt(str(file_path))


def _build_fallback_doc_payload(document: Document, file_path: Path) -> dict:
    try:
        full_text = _extract_text_for_fallback(file_path)
    except Exception:
        logger.exception("Fallback text extraction failed for %s", file_path)
        full_text = ""
    now = datetime.utcnow().isoformat()
    short = (full_text or "").strip()
    title = Path(document.filename).stem
    section_content = short[:3000]
    chunk_content = short[:2500]
    return {
        "id": str(document.id),
        "file": document.filename,
        "title": title,
        "abstract": short[:1200],
        "authors": [],
        "keywords": [],
        "year": None,
        "journal": None,
        "language": "vi",
        "doi": None,
        "full_text": short,
        "sections": [
            {
                "name": "content",
                "order": 0,
                "content": section_content,
            }
        ] if section_content else [],
        "chunks": [
            {
                "chunk_id": 0,
                "page": None,
                "text": chunk_content,
            }
        ] if chunk_content else [],
        "figures": [],
        "tables": [],
        "formulas": [],
        "created_at": now,
    }


def _to_unified_document(doc_payload: dict):
    from ingestion.schema.document_schema import UnifiedDocument, Section, Reference

    sections = []
    for i, sec in enumerate(doc_payload.get("sections") or []):
        if not isinstance(sec, dict):
            continue
        sections.append(
            Section(
                name=str(sec.get("name") or f"section-{i}"),
                content=str(sec.get("content") or ""),
                order=int(sec.get("order", i)),
                level=int(sec.get("level", 1)),
                section_type=sec.get("section_type"),
                parent_section=sec.get("parent_section"),
            )
        )

    references = []
    for ref in doc_payload.get("references") or []:
        if not isinstance(ref, dict):
            continue
        references.append(
            Reference(
                raw_text=str(ref.get("raw_text") or ref.get("title") or ""),
                doi=ref.get("doi"),
                title=ref.get("title"),
                authors=[str(a) for a in (ref.get("authors") or []) if str(a).strip()],
                year=ref.get("year"),
                internal_doc_id=ref.get("internal_doc_id"),
            )
        )

    return UnifiedDocument(
        title=str(doc_payload.get("title") or "Unknown"),
        authors=[str(a) for a in (doc_payload.get("authors") or []) if str(a).strip()],
        year=doc_payload.get("year"),
        journal=doc_payload.get("journal"),
        doi=doc_payload.get("doi"),
        keywords=[str(k) for k in (doc_payload.get("keywords") or []) if str(k).strip()],
        doc_id=str(doc_payload.get("id") or ""),
        abstract=str(doc_payload.get("abstract") or ""),
        full_text=str(doc_payload.get("full_text") or ""),
        sections=sections,
        references=references,
        source_file=str(doc_payload.get("file") or ""),
        source_type=str(doc_payload.get("source_type") or "pdf"),
        language=doc_payload.get("language"),
        page_count=doc_payload.get("page_count"),
        citation_count=doc_payload.get("citation_count"),
    )


def _auto_build_graph(document: Document, db: Session, doc_payload: dict) -> bool:
    if os.getenv("AUTO_BUILD_GRAPH", "true").lower() != "true":
        return True

    graph_mode = os.getenv("GRAPH_BUILD_MODE", "lightweight").strip().lower()
    if graph_mode in {"lightweight", "light", "fast"}:
        try:
            title = str(doc_payload.get("title") or document.filename or f"document-{document.id}")
            keywords = [str(k).strip() for k in (doc_payload.get("keywords") or []) if str(k).strip()]
            sections = doc_payload.get("sections") or []
            refs = doc_payload.get("references") or []

            nodes: list[dict] = [{"id": f"doc:{document.id}", "label": title, "type": "Document"}]
            edges: list[dict] = []

            for kw in keywords[:20]:
                nid = f"kw:{kw.lower()}"
                nodes.append({"id": nid, "label": kw, "type": "Keyword"})
                edges.append({"source": f"doc:{document.id}", "target": nid, "relation": "HAS_KEYWORD"})

            for i, sec in enumerate(sections[:30]):
                if not isinstance(sec, dict):
                    continue
                name = str(sec.get("name") or f"section-{i}").strip()
                if not name:
                    continue
                nid = f"sec:{document.id}:{i}"
                nodes.append({"id": nid, "label": name, "type": "Section"})
                edges.append({"source": f"doc:{document.id}", "target": nid, "relation": "HAS_SECTION"})

            for i, ref in enumerate(refs[:20]):
                if not isinstance(ref, dict):
                    continue
                label = str(ref.get("title") or ref.get("raw_text") or "").strip()
                if not label:
                    continue
                nid = f"ref:{document.id}:{i}"
                nodes.append({"id": nid, "label": label[:160], "type": "Reference"})
                edges.append({"source": f"doc:{document.id}", "target": nid, "relation": "CITES"})

            graph = db.query(DocumentGraph).filter(DocumentGraph.document_id == document.id).first()
            if graph is None:
                graph = DocumentGraph(document_id=document.id)
                db.add(graph)
            graph.nodes = nodes
            graph.edges = edges
            db.commit()
            logger.info(
                "Lightweight graph built for document_id=%s nodes=%d edges=%d",
                document.id,
                len(nodes),
                len(edges),
            )
            return True
        except Exception:
            db.rollback()
            logger.exception("Lightweight graph build failed for document_id=%s", document.id)
            return False

    try:
        from ai_module.kg.entity_extractor import create_extractor_from_env
        from ai_module.kg.graph_builder import GraphBuilder
        from storage.graph_db.neo4j_client import Neo4jClient, Neo4jConfig

        neo4j_cfg = Neo4jConfig(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            username=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "password"),
            database=os.getenv("NEO4J_USER_DOC_DB", os.getenv("NEO4J_DATABASE", "neo4j")),
        )
        client = Neo4jClient(neo4j_cfg)
        client.connect()
        try:
            client.ensure_schema()
            extractor = create_extractor_from_env()
            unified_doc = _to_unified_document(doc_payload)
            entities = extractor.extract(unified_doc)
            builder = GraphBuilder(client)
            paper_id = builder.build(unified_doc, entities, relations=None, chunk_map=None)

            nodes = client.execute_read(
                """
                MATCH (p:Paper {id: $paper_id})-[r]-(n)
                RETURN p, r, n
                LIMIT 300
                """,
                {"paper_id": paper_id},
            )
            node_map: dict[str, dict] = {}
            edges: list[dict] = []
            for row in nodes:
                for key in ("p", "n"):
                    nd = row.get(key)
                    if not nd:
                        continue
                    nid = str(nd.get("id") or getattr(nd, "id", ""))
                    if not nid or nid in node_map:
                        continue
                    labels = list(getattr(nd, "labels", []) or [])
                    node_map[nid] = {
                        "id": nid,
                        "label": str(nd.get("title") or nd.get("name") or nid),
                        "type": labels[0] if labels else "Node",
                    }
                rel = row.get("r")
                p = row.get("p")
                n = row.get("n")
                if rel and p and n:
                    edges.append(
                        {
                            "source": str(p.get("id") or getattr(p, "id", "")),
                            "target": str(n.get("id") or getattr(n, "id", "")),
                            "relation": str(getattr(rel, "type", "")),
                        }
                    )

            graph = db.query(DocumentGraph).filter(DocumentGraph.document_id == document.id).first()
            if graph is None:
                graph = DocumentGraph(document_id=document.id)
                db.add(graph)
            graph.nodes = list(node_map.values())
            graph.edges = edges
            db.commit()
            logger.info("Auto graph build done for document_id=%s paper_id=%s", document.id, paper_id)
            return True
        finally:
            client.close()
    except Exception:
        db.rollback()
        logger.exception("Auto graph build failed for document_id=%s", document.id)
        return False


def run_ingestion_for_document(document_id: int, use_lm: bool = True) -> None:
    db = SessionLocal()
    try:
        document = (
            db.query(Document)
            .filter(Document.id == document_id, Document.is_deleted == False)
            .first()
        )
        if document is None:
            logger.warning("Ingestion skipped: document %s not found", document_id)
            return

        job = (
            db.query(DocumentJob)
            .filter(
                DocumentJob.document_id == document.id,
                DocumentJob.job_type == "process_document",
            )
            .order_by(DocumentJob.created_at.desc())
            .first()
        )
        if job is None:
            job = DocumentJob(
                document_id=document.id,
                job_type="process_document",
                requested_by_user_id=document.user_id,
                payload={"filename": document.filename, "file_type": document.file_type},
            )
            db.add(job)
            db.commit()
            db.refresh(job)

        candidate_paths = [
            (PROJECT_ROOT / "uploaded_files" / document.filename).resolve(),
            (PROJECT_ROOT / "backend" / "uploaded_files" / document.filename).resolve(),
        ]
        file_path = next((p for p in candidate_paths if p.exists()), candidate_paths[0])
        if not file_path.exists():
            document.status = "failed"
            job.status = "failed"
            job.error_message = f"Source file not found: {file_path}"
            job.completed_at = datetime.utcnow()
            db.commit()
            return

        document.status = "processing"
        job.status = "running"
        job.last_started_at = datetime.utcnow()
        db.commit()

        result = run_pipeline(
            file_path=str(file_path),
            use_lm=use_lm,
            dry_run_enrich=False,
        )

        if not result.success or result.doc is None:
            fallback_doc = _build_fallback_doc_payload(document, file_path)
            fallback_doc = _repair_metadata_from_existing_json(document, fallback_doc)
            json_path = _save_processed_json(document, fallback_doc)
            _upsert_metadata(db, document.id, fallback_doc)
            _upsert_artifact(db, document.id, _artifact_uri_for_db(json_path), json_path.stat().st_size)
            document.status = "parsed"
            db.commit()
            graph_ok = _auto_build_graph(document, db, fallback_doc)
            document.status = "processed" if graph_ok else "failed"
            document.raw_text = _strip_nul((fallback_doc.get("full_text") or "")[:10000])
            job.status = "done" if graph_ok else "failed"
            job.error_message = (
                ("\n".join(result.errors) if result.errors else f"Failed at {result.failed_at}")
                if graph_ok
                else "Graph build failed after ingestion fallback."
            )
            job.result = {
                "success": bool(graph_ok),
                "fallback": True,
                "failed_at": result.failed_at,
                "errors": result.errors,
                "duration_s": result.duration_s,
                "artifact_uri": _artifact_uri_for_db(json_path),
                "graph_built": graph_ok,
            }
            job.completed_at = datetime.utcnow()
            db.commit()
            logger.warning("Ingestion fallback JSON generated for document_id=%s", document.id)
            return

        doc_payload = _serialize_doc_for_json(result.doc)
        doc_payload = _repair_metadata_from_existing_json(document, doc_payload)
        doc_payload = _sanitize_payload_strings(doc_payload)
        json_path = _save_processed_json(document, doc_payload)
        _upsert_metadata(db, document.id, doc_payload)
        _upsert_artifact(db, document.id, _artifact_uri_for_db(json_path), json_path.stat().st_size)
        document.status = "parsed"
        db.commit()
        graph_ok = _auto_build_graph(document, db, doc_payload)

        document.status = "processed" if graph_ok else "failed"
        document.raw_text = _strip_nul((doc_payload.get("full_text") or "")[:10000])
        job.status = "done" if graph_ok else "failed"
        job.error_message = None if graph_ok else "Graph build failed after ingestion."
        job.result = {
            "success": bool(graph_ok),
            "duration_s": result.duration_s,
            "artifact_uri": _artifact_uri_for_db(json_path),
            "sections": len(doc_payload.get("sections") or []),
            "figures": len(doc_payload.get("figures") or []),
            "tables": len(doc_payload.get("tables") or []),
            "graph_built": graph_ok,
        }
        job.completed_at = datetime.utcnow()
        db.commit()
        logger.info("Ingestion done for document_id=%s", document.id)
    except Exception as e:
        logger.exception("Background ingestion crashed for document_id=%s: %s", document_id, e)
        try:
            job = (
                db.query(DocumentJob)
                .filter(
                    DocumentJob.document_id == document_id,
                    DocumentJob.job_type == "process_document",
                )
                .order_by(DocumentJob.created_at.desc())
                .first()
            )
            document = db.query(Document).filter(Document.id == document_id).first()
            if document:
                document.status = "failed"
            if job:
                job.status = "failed"
                job.error_message = f"{e}\n{traceback.format_exc(limit=3)}"
                job.completed_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
