from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Set

from ai_module.embedding.embedding_service import EmbeddingService
from ai_module.recommendation.hybrid_recommender import extract_methods


METHOD_HINTS = [
    "arduino",
    "denavit-hartenberg",
    "d-h",
    "lagrange",
    "rsbs",
    "flutter",
    "cfd",
    "wind tunnel",
    "in 3d",
    "3d print",
    "servo",
    "bluetooth",
]


def _safe(v: Any) -> str:
    return str(v or "").strip()


def _norm(v: str) -> str:
    return " ".join(_safe(v).lower().split())


def _as_list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [_safe(x) for x in v if _safe(x)]
    if isinstance(v, str) and _safe(v):
        return [_safe(v)]
    return []


def _paper_title(doc: Dict[str, Any], file_name: str) -> str:
    m = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return _safe(doc.get("title")) or _safe((m or {}).get("title")) or file_name


def _paper_abstract(doc: Dict[str, Any]) -> str:
    m = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return _safe(doc.get("abstract")) or _safe((m or {}).get("abstract"))


def _paper_authors(doc: Dict[str, Any]) -> List[str]:
    m = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return _as_list((m or {}).get("authors"))


def _paper_keywords(doc: Dict[str, Any]) -> List[str]:
    m = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return _as_list((m or {}).get("keywords"))


def _paper_text_blob(doc: Dict[str, Any], file_name: str) -> str:
    title = _paper_title(doc, file_name=file_name)
    abstract = _paper_abstract(doc)
    kws = _paper_keywords(doc)
    sections = doc.get("sections") if isinstance(doc.get("sections"), list) else []
    section_snips: List[str] = []
    for s in sections[:8]:
        if not isinstance(s, dict):
            continue
        name = _safe(s.get("name"))
        content = _safe(s.get("content"))
        if not content:
            continue
        section_snips.append((name + "\n" + content[:800]).strip())
    parts = [f"Title: {title}"]
    if abstract:
        parts.append(f"Abstract: {abstract}")
    if kws:
        parts.append("Keywords: " + ", ".join(kws))
    parts.extend(section_snips)
    return "\n\n".join([p for p in parts if p]).strip()


def _paper_methods(doc: Dict[str, Any], text_blob: str) -> List[str]:
    found: Set[str] = set(extract_methods(text_blob))
    low = _norm(text_blob)
    for h in METHOD_HINTS:
        if h in low:
            found.add(h)
    for kw in _paper_keywords(doc):
        lkw = _norm(kw)
        for h in METHOD_HINTS:
            if h in lkw:
                found.add(h)
    return sorted(found)


@dataclass
class VirtualGraphRecommender:
    embedding: EmbeddingService

    def build(self, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        papers: Dict[str, Dict[str, Any]] = {}
        node_types: Dict[str, str] = {}
        edges: List[Dict[str, str]] = []
        author_to_papers: Dict[str, Set[str]] = {}
        method_to_papers: Dict[str, Set[str]] = {}
        keyword_to_papers: Dict[str, Set[str]] = {}

        for i, doc in enumerate(docs):
            file_name = _safe(doc.get("file")) or f"paper_{i}.json"
            pid = f"paper::{file_name}"
            title = _paper_title(doc, file_name=file_name)
            abstract = _paper_abstract(doc)
            authors = _paper_authors(doc)
            keywords = _paper_keywords(doc)
            text_blob = _paper_text_blob(doc, file_name=file_name)
            methods = _paper_methods(doc, text_blob=text_blob)

            papers[pid] = {
                "paper_id": pid,
                "file": file_name,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "keywords": keywords,
                "methods": methods,
                "text": text_blob,
            }
            node_types[pid] = "paper"

            for a in authors:
                aid = f"author::{_norm(a)}"
                node_types[aid] = "author"
                edges.append({"source": pid, "target": aid, "relation": "has_author"})
                author_to_papers.setdefault(aid, set()).add(pid)
            for m in methods:
                mid = f"method::{_norm(m)}"
                node_types[mid] = "method"
                edges.append({"source": pid, "target": mid, "relation": "uses_method"})
                method_to_papers.setdefault(mid, set()).add(pid)
            for k in keywords:
                kid = f"keyword::{_norm(k)}"
                node_types[kid] = "keyword"
                edges.append({"source": pid, "target": kid, "relation": "has_keyword"})
                keyword_to_papers.setdefault(kid, set()).add(pid)

        return {
            "papers": papers,
            "node_types": node_types,
            "edges": edges,
            "author_to_papers": {k: sorted(v) for k, v in author_to_papers.items()},
            "method_to_papers": {k: sorted(v) for k, v in method_to_papers.items()},
            "keyword_to_papers": {k: sorted(v) for k, v in keyword_to_papers.items()},
        }

    def recommend(
        self,
        graph: Dict[str, Any],
        top_k: int = 5,
        query: str | None = None,
        seed_file: str | None = None,
    ) -> Dict[str, Any]:
        papers: Dict[str, Dict[str, Any]] = graph["papers"]
        paper_ids = list(papers.keys())
        if not paper_ids:
            return {"task": "virtual_graph_recommendation", "recommendations": []}

        seed_pid = f"paper::{seed_file}" if seed_file else None
        if seed_pid and seed_pid not in papers:
            seed_pid = None

        # Semantic score (query mode only).
        sem_scores: Dict[str, float] = {}
        if query:
            qvec = self.embedding.embed_query(query)
            dvecs = self.embedding.embed_texts([papers[pid]["text"] for pid in paper_ids])
            import numpy as np

            q = np.array(qvec, dtype=np.float32)
            for pid, dv in zip(paper_ids, dvecs):
                v = np.array(dv, dtype=np.float32)
                score = float(np.dot(q, v))
                sem_scores[pid] = max(0.0, min(1.0, (score + 1.0) / 2.0))

        ranked: List[Dict[str, Any]] = []
        for pid in paper_ids:
            p = papers[pid]
            if seed_pid and pid == seed_pid:
                continue

            graph_score = 0.0
            if seed_pid:
                seed = papers[seed_pid]
                sa = {_norm(x) for x in seed.get("authors", [])}
                sm = {_norm(x) for x in seed.get("methods", [])}
                sk = {_norm(x) for x in seed.get("keywords", [])}
                pa = {_norm(x) for x in p.get("authors", [])}
                pm = {_norm(x) for x in p.get("methods", [])}
                pk = {_norm(x) for x in p.get("keywords", [])}
                graph_score += 3.0 * len(sa & pa)
                graph_score += 2.0 * len(sm & pm)
                graph_score += 1.0 * len(sk & pk)
            elif query:
                qn = _norm(query)
                if any(_norm(a) in qn for a in p.get("authors", [])):
                    graph_score += 1.5
                if any(_norm(m) in qn for m in p.get("methods", [])):
                    graph_score += 1.5
                if any(_norm(k) in qn for k in p.get("keywords", [])):
                    graph_score += 1.0

            sem = sem_scores.get(pid, 0.0)
            final_score = 0.65 * sem + 0.35 * min(1.0, graph_score / 4.0) if query else min(1.0, graph_score / 6.0)
            ranked.append(
                {
                    "paper_id": pid,
                    "file": p.get("file"),
                    "title": p.get("title"),
                    "authors": p.get("authors", []),
                    "methods": p.get("methods", []),
                    "keywords": p.get("keywords", []),
                    "score": round(float(final_score), 6),
                    "score_breakdown": {
                        "semantic": round(float(sem), 6),
                        "graph_raw": round(float(graph_score), 6),
                    },
                }
            )

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return {
            "task": "virtual_graph_recommendation",
            "seed_file": seed_file,
            "query": query,
            "top_k": top_k,
            "num_papers": len(paper_ids),
            "recommendations": ranked[:top_k],
        }

