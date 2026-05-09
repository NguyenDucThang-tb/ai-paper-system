"""
lm_metadata_extractor.py
------------------------
Extract metadata using local LLM (Ollama) natively inside the ingestion pipeline.
"""

import json
import logging
import re
from dataclasses import replace
from typing import Optional

from ingestion.schema.document_schema import UnifiedDocument

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
DEFAULT_MODEL = "qwen2.5:7b"
TEMPERATURE = 0.1
TIMEOUT = 120  # seconds
MAX_INPUT_CHARS = 3000

METADATA_PROMPT_TEMPLATE = """Bạn là trợ lý trích xuất metadata từ bài báo khoa học.
Trích xuất JSON với các trường sau từ đoạn text bài báo:
{{
  "title": "tiêu đề bài báo",
  "authors": ["tên tác giả 1", "tên tác giả 2"],
  "abstract": "tóm tắt bài báo",
  "keywords": ["từ khóa 1", "từ khóa 2"],
  "year": 2024,
  "journal": "tên tạp chí hoặc hội nghị",
  "language": "vi hoặc en"
}}

Quy tắc:
- Chỉ trả JSON, không giải thích.
- Nếu bài báo có cả tiêu đề tiếng Việt và tiếng Anh, LUÔN ƯU TIÊN trích xuất tiêu đề tiếng Việt cho trường 'title'.
- Nếu bài báo có cả tóm tắt tiếng Việt và tiếng Anh, LUÔN ƯU TIÊN tiếng Việt cho trường 'abstract'.
- Nếu không tìm thấy trường nào, để giá trị null.
- authors là mảng string, mỗi phần tử là tên đầy đủ 1 tác giả.
- keywords là mảng string.
- year là số nguyên (int), không phải string.

TEXT:
{text}"""

# ---------------------------------------------------------------------------
# Core Logic
# ---------------------------------------------------------------------------

def is_ollama_available(model: str = DEFAULT_MODEL) -> bool:
    """Kiểm tra xem Ollama có đang chạy và model có sẵn không."""
    try:
        import requests
        response = requests.get(
            f"{OLLAMA_BASE_URL}/api/tags",
            timeout=5,
        )
        if response.status_code != 200:
            return False
        tags = response.json()
        models = [m.get("name", "") for m in tags.get("models", [])]
        return any(model in m or m.startswith(model.split(":")[0]) for m in models)
    except Exception:
        return False

def _generate(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Gọi API generate của Ollama."""
    try:
        import requests
    except ImportError:
        raise ImportError("requests not installed. Run: pip install requests")
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
        },
    }
    try:
        response = requests.post(OLLAMA_GENERATE_URL, json=payload, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        logger.debug(f"Ollama generate failed: {e}")
        return ""

def _parse_json_response(text: str) -> Optional[dict]:
    """Parse JSON trả về từ Ollama."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    json_block = re.search(r"```(?:json)?\s*\n?(.+?)\n?```", text, re.DOTALL)
    if json_block:
        try:
            return json.loads(json_block.group(1).strip())
        except json.JSONDecodeError:
            pass

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None

def extract_metadata_via_lm(doc: UnifiedDocument, model: str = DEFAULT_MODEL) -> UnifiedDocument:
    """
    Extract metadata bằng LM và merge vào UnifiedDocument.
    Override kết quả của regex nếu LM tìm thấy dữ liệu tốt hơn.
    """
    if not is_ollama_available(model):
        logger.warning(f"Ollama or model '{model}' not available. Skipping LM metadata extraction.")
        return doc

    text = doc.full_text or ""
    if not text or len(text.strip()) < 100:
        logger.debug("Text too short for LM metadata extraction")
        return doc

    truncated = text[:MAX_INPUT_CHARS]
    prompt = METADATA_PROMPT_TEMPLATE.format(text=truncated)
    
    raw_response = _generate(prompt, model)
    if not raw_response:
        return doc
        
    meta = _parse_json_response(raw_response)
    if not meta:
        logger.debug("Could not parse JSON from LM response")
        return doc
        
    updates = {}
    
    # Title override
    title = meta.get("title")
    if isinstance(title, str) and title.strip() and title.strip() != "Unknown":
        if doc.title != title.strip():
            updates["title"] = title.strip()
            
    # Authors override
    authors = meta.get("authors")
    if isinstance(authors, list):
        clean_authors = [str(a).strip() for a in authors if isinstance(a, str) and a.strip()]
        if clean_authors and doc.authors != clean_authors:
            logger.info(f"LM overriding authors: {doc.authors} -> {clean_authors}")
            updates["authors"] = clean_authors
            
    # Abstract override
    abstract = meta.get("abstract")
    if isinstance(abstract, str) and len(abstract.strip()) > 50:
        if doc.abstract != abstract.strip():
            updates["abstract"] = abstract.strip()
            
    # Keywords
    keywords = meta.get("keywords")
    if isinstance(keywords, list) and not doc.keywords:
        clean_kw = [str(k).strip() for k in keywords if isinstance(k, str) and k.strip()]
        if clean_kw:
            updates["keywords"] = clean_kw
            
    # Year
    year = meta.get("year")
    if isinstance(year, int) and 1900 <= year <= 2100 and doc.year is None:
        updates["year"] = year
    elif isinstance(year, str) and doc.year is None:
        try:
            y = int(year)
            if 1900 <= y <= 2100:
                updates["year"] = y
        except ValueError:
            pass

    # Journal
    journal = meta.get("journal")
    if isinstance(journal, str) and journal.strip() and journal.strip().lower() != "null" and doc.journal is None:
        updates["journal"] = journal.strip()
        
    # Language
    language = meta.get("language")
    if isinstance(language, str) and language.strip().lower() in ("vi", "en") and doc.language is None:
        updates["language"] = language.strip().lower()

    if updates:
        logger.info(f"LM metadata extraction enriched fields: {list(updates.keys())}")
        return replace(doc, **updates)
        
    logger.debug("LM metadata — all fields already filled & valid")
    return doc
