from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set

import numpy as np

from ai_module.embedding.embedding_service import EmbeddingService
from ai_module.inference.inference_config import InferenceConfig
from ai_module.retrieval.vector_retriever import FAISSStore

METHOD_KEYWORDS = [
    "transformer",
    "rag",
    "bert",
    "gpt",
    "cross-encoder",
    "bi-encoder",
    "event extraction",
    "graph",
    "lora",
    "fine-tune",
    "retrieval",
]



def normalize_key(text: str) -> str:
    return " ".join((text or "").lower().strip().split())



def _split_people(text: str) -> List[str]:
    parts = re.split(r"[,;]| and | & ", text)
    return [p.strip() for p in parts if p.strip()]



def extract_title(text: str, fallback_file: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines[:8]:
        if 3 <= len(ln) <= 180 and not ln.lower().startswith(("abstract", "introduction", "keywords")):
            return ln.lstrip("\ufeff")
    return fallback_file



def extract_authors(text: str) -> List[str]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines[:20]:
        if "author" in ln.lower() or "tác giả" in ln.lower():
            tail = ln.split(":", 1)[-1]
            return sorted(set(_split_people(tail)))
    return []



def extract_year(text: str) -> int | None:
    m = re.findall(r"\b(19\d{2}|20\d{2})\b", text or "")
    if not m:
        return None
    years = [int(x) for x in m]
    years = [y for y in years if 1990 <= y <= 2100]
    return max(years) if years else None



def extract_methods(text: str, max_methods: int = 10) -> List[str]:
    tl = (text or "").lower()
    out = []
    for kw in METHOD_KEYWORDS:
        if kw in tl:
            out.append(kw)
    return sorted(set(out))[:max_methods]



def build_paper_record(doc: Dict[str, Any], idx: int) -> Dict[str, Any]:
    text = str(doc.get("text", ""))
    file = str(doc.get("file", f"paper_{idx}.txt"))
    return {
        "paper_id": f"paper_{idx}",
        "title": extract_title(text, fallback_file=file),
        "authors": extract_authors(text),
        "year": extract_year(text),
        "methods": extract_methods(text),
        "file": file,
        "text": text,
    }



def build_recommendation_index(documents: List[Dict[str, Any]], embedding_service: EmbeddingService, index_path: str) -> Dict[str, Any]:
    records = [build_paper_record(doc, i) for i, doc in enumerate(documents)]
    vectors = embedding_service.embed_texts([r["text"] for r in records])

    metadata = []
    for r in records:
        metadata.append({
            "paper_id": r["paper_id"],
            "file": r["file"],
            "title": r["title"],
            "authors": r["authors"],
            "methods": r["methods"],
            "year": r["year"],
            "text": r["text"],
        })

    store = FAISSStore()
    store.build(vectors, metadata)

    out_dir = Path(index_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    np.save(out_dir / "vectors.npy", np.array(vectors, dtype=np.float32))
    (out_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "paper_records.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    author_index: Dict[str, List[str]] = defaultdict(list)
    method_index: Dict[str, List[str]] = defaultdict(list)
    for r in records:
        pid = r["paper_id"]
        for a in r["authors"]:
            author_index[normalize_key(a)].append(pid)
        for m in r["methods"]:
            method_index[normalize_key(m)].append(pid)

    (out_dir / "author_index.json").write_text(json.dumps(author_index, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "method_index.json").write_text(json.dumps(method_index, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"num_papers": len(records), "index_path": str(out_dir)}



def load_recommendation_index(index_path: str) -> Dict[str, Any]:
    p = Path(index_path)
    vectors = np.load(p / "vectors.npy")
    metadata = json.loads((p / "metadata.json").read_text(encoding="utf-8"))
    records = json.loads((p / "paper_records.json").read_text(encoding="utf-8"))
    author_index = json.loads((p / "author_index.json").read_text(encoding="utf-8"))
    method_index = json.loads((p / "method_index.json").read_text(encoding="utf-8"))

    store = FAISSStore()
    store.build(vectors.tolist(), metadata)
    return {
        "store": store,
        "paper_records": records,
        "author_index": author_index,
        "method_index": method_index,
    }



def _year_score(year: int | None, min_year: int, max_year: int) -> float:
    if year is None:
        return 0.0
    if min_year == max_year:
        return 1.0
    return max(0.0, min(1.0, (int(year) - min_year) / float(max_year - min_year)))



def recommend_papers(
    index_path: str,
    embedding_service: EmbeddingService | None,
    top_k: int = 5,
    author: str | None = None,
    method: str | None = None,
    query: str | None = None,
    mode: str = "hybrid",
) -> Dict[str, Any]:
    data = load_recommendation_index(index_path)
    store = data["store"]
    records = data["paper_records"]
    author_idx = data["author_index"]
    method_idx = data["method_index"]
    by_id = {r["paper_id"]: r for r in records}

    years = [r["year"] for r in records if r.get("year") is not None]
    min_year = min(years) if years else 2000
    max_year = max(years) if years else 2000

    qtxt = (query or "").strip()
    if author:
        qtxt += f" author {author}"
    if method:
        qtxt += f" method {method}"

    sem_scores = {}
    if qtxt and embedding_service is not None:
        qvec = embedding_service.embed_query(qtxt)
        sem = store.search(qvec, top_k=max(40, top_k * 20))
        for s in sem:
            sem_scores[s["paper_id"]] = max(sem_scores.get(s["paper_id"], 0.0), max(0.0, min(1.0, (s["score"] + 1.0) / 2.0)))

    author_keys = [k for k in author_idx.keys() if author and normalize_key(author) in k]
    method_keys = [k for k in method_idx.keys() if method and normalize_key(method) in k]

    author_cands: Set[str] = set()
    for k in author_keys:
        author_cands.update(author_idx.get(k, []))
    method_cands: Set[str] = set()
    for k in method_keys:
        method_cands.update(method_idx.get(k, []))

    sem_cands = set(sem_scores.keys())
    if mode == "by-author":
        cands = author_cands or sem_cands
        w_sem, w_a, w_m, w_r = 0.25, 0.65, 0.0, 0.10
    elif mode == "by-method":
        cands = method_cands or sem_cands
        w_sem, w_a, w_m, w_r = 0.35, 0.0, 0.55, 0.10
    else:
        cands = author_cands | method_cands | sem_cands
        if not cands:
            cands = set(by_id.keys())
        w_sem, w_a, w_m, w_r = 0.40, 0.20, 0.30, 0.10

    ranked = []
    for pid in cands:
        rec = by_id.get(pid)
        if not rec:
            continue
        sem = sem_scores.get(pid, 0.0)
        a = 1.0 if pid in author_cands else 0.0
        m = 1.0 if pid in method_cands else 0.0
        r = _year_score(rec.get("year"), min_year, max_year)
        score = w_sem * sem + w_a * a + w_m * m + w_r * r
        ranked.append((score, {
            "paper_id": pid,
            "title": rec.get("title"),
            "authors": rec.get("authors", []),
            "year": rec.get("year"),
            "methods": rec.get("methods", []),
            "file": rec.get("file"),
            "score": round(score, 6),
            "score_breakdown": {
                "semantic": round(sem, 6),
                "author_match": round(a, 6),
                "method_match": round(m, 6),
                "recency": round(r, 6),
            },
        }))

    ranked.sort(key=lambda x: x[0], reverse=True)
    recs = [x[1] for x in ranked[:top_k]]
    return {
        "task": "paper_recommendation",
        "mode": mode,
        "query": query,
        "author": author,
        "method": method,
        "top_k": top_k,
        "num_candidates": len(cands),
        "recommendations": recs,
    }


class HybridRecommender:
    def __init__(self, config: InferenceConfig) -> None:
        self.embedding = EmbeddingService(config)

    def recommend(self, index_path: str, top_k: int = 5, query: str | None = None, author: str | None = None, method: str | None = None) -> Dict[str, Any]:
        return recommend_papers(index_path=index_path, embedding_service=self.embedding, top_k=top_k, query=query, author=author, method=method, mode="hybrid")
