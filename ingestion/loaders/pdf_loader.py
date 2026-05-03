"""
pdf_loader.py
-------------
Load academic PDF papers into UnifiedDocument format.

Strategy:
  - PyMuPDF  → tables, figures, images, raw text per page
  - GROBID   → title, authors, abstract, sections, references (structure)
  - Merge    → UnifiedDocument
"""

import base64
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import fitz  # PyMuPDF

from ingestion.schema.document_schema import (
    Figure,
    Reference,
    Section,
    Table,
    UnifiedDocument,
)

logger = logging.getLogger(__name__)

# GROBID TEI namespace
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

# Known academic section names for section_type tagging
SECTION_TYPE_MAP = {
    "acknowledgements": "acknowledgment",
    "acknowledgement": "acknowledgment",
    "acknowledgment": "acknowledgment",
    "experimental results": "result",
    "related work": "related_work",
    "future work": "future_work",
    "methodology": "method",
    "conclusions": "conclusion",
    "conclusion": "conclusion",
    "discussion": "discussion",
    "experiments": "experiment",
    "experiment": "experiment",
    "evaluation": "experiment",
    "background": "background",
    "references": "references",
    "introduction": "introduction",
    "approach": "method",
    "results": "result",
    "abstract": "abstract",
    "method": "method",
    "result": "result",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_pdf(file_path: str, grobid_url: str = "http://localhost:8070") -> UnifiedDocument:
    """
    Load an academic PDF into UnifiedDocument format.

    Args:
        file_path:   Path to the PDF file.
        grobid_url:  URL of the running GROBID server.

    Returns:
        UnifiedDocument with all extracted fields populated.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        RuntimeError:      If both GROBID and fallback extraction fail.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")

    logger.info("Loading PDF: %s", file_path)

    # --- Step 1: PyMuPDF — extract tables, figures, page count ---
    pymupdf_data = _extract_with_pymupdf(path)

    # --- Step 2: GROBID — extract structure ---
    grobid_data = _extract_with_grobid(path, grobid_url)

    # --- Step 3: Merge into UnifiedDocument ---
    doc = _merge(pymupdf_data, grobid_data, file_path)

    logger.info(
        "Loaded: '%s' — %d sections, %d tables, %d figures",
        doc.title, len(doc.sections), len(doc.tables), len(doc.figures),
    )
    return doc


# ---------------------------------------------------------------------------
# PyMuPDF extraction
# ---------------------------------------------------------------------------

def _extract_with_pymupdf(path: Path) -> dict:
    """Extract tables, figures, images and page count using PyMuPDF."""
    result = {
        "page_count": 0,
        "tables": [],
        "figures": [],
        "raw_text_by_page": [],
    }

    try:
        doc = fitz.open(str(path))
        result["page_count"] = len(doc)

        for page_num, page in enumerate(doc):
            # Raw text (fallback nếu GROBID fail)
            result["raw_text_by_page"].append(page.get_text())

            # Extract tables
            try:
                page_tables = page.find_tables()
            except AttributeError:
                logger.warning("page.find_tables() not available — upgrade PyMuPDF >= 1.23.0")
                page_tables = []

            for table in page_tables:
                try:
                    df = table.to_pandas()
                    headers = list(df.columns.astype(str))
                    data = df.values.tolist()
                    result["tables"].append(Table(
                        caption=f"Table on page {page_num + 1}",
                        index=len(result["tables"]) + 1,
                        headers=headers,
                        data=[[str(cell) if cell is not None else "" for cell in row]
                              for row in data],
                    ))
                except Exception as e:
                    logger.debug("Table extraction failed on page %d: %s", page_num + 1, e)

            # Extract figures (image blocks) with base64 data
            try:
                image_list = page.get_images(full=True)
                for img in image_list:
                    try:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        b64 = base64.b64encode(image_bytes).decode("utf-8")
                        result["figures"].append(Figure(
                            caption=f"Figure on page {page_num + 1}",
                            index=len(result["figures"]) + 1,
                            figure_type="image",
                            base64_data=b64,
                        ))
                    except Exception as e:
                        logger.debug("Figure extraction failed on page %d: %s", page_num + 1, e)
            except Exception as e:
                logger.debug("Image list extraction failed on page %d: %s", page_num + 1, e)

        doc.close()

    except Exception as e:
        logger.error("PyMuPDF extraction failed: %s", e)

    return result


# ---------------------------------------------------------------------------
# GROBID extraction
# ---------------------------------------------------------------------------

def _extract_with_grobid(path: Path, grobid_url: str) -> dict:
    """Extract structured content using GROBID TEI XML."""
    result = {
        "title": "",
        "authors": [],
        "abstract": "",
        "year": None,
        "journal": None,
        "doi": None,
        "keywords": [],
        "sections": [],
        "references": [],
        "success": False,
    }

    try:
        from grobid_client.grobid_client import GrobidClient

        client = GrobidClient(
            grobid_server=grobid_url,
            batch_size=1,
            sleep_time=5,
            timeout=60,
            config_path=None,
        )

        # Process single PDF → TEI XML
        _, status, tei_text = client.process_pdf(
            "processFulltextDocument",
            str(path),
            generateIDs=False,
            consolidate_header=True,
            consolidate_citations=False,
            include_raw_citations=False,
            include_raw_affiliations=False,
            tei_coordinates=False,
            segment_sentences=False,
        )

        if status != 200 or not tei_text:
            logger.warning("GROBID returned status %s", status)
            return result

        result.update(_parse_tei_xml(tei_text))
        result["success"] = True

    except ImportError:
        logger.warning("grobid-client-python not installed. Install: pip install grobid-client-python")
    except Exception as e:
        logger.error("GROBID extraction failed: %s", e)

    return result


def _parse_tei_xml(tei_text: str) -> dict:
    """Parse GROBID TEI XML into structured dict."""
    data = {
        "title": "",
        "authors": [],
        "abstract": "",
        "year": None,
        "journal": None,
        "doi": None,
        "keywords": [],
        "sections": [],
        "references": [],
    }

    try:
        root = ET.fromstring(tei_text)
        header = root.find(".//tei:teiHeader", TEI_NS)
        body = root.find(".//tei:body", TEI_NS)

        if header is not None:
            # Title
            title_el = header.find(".//tei:titleStmt/tei:title", TEI_NS)
            if title_el is not None and title_el.text:
                data["title"] = title_el.text.strip()

            # Authors
            for author in header.findall(".//tei:persName", TEI_NS):
                forename = author.find("tei:forename", TEI_NS)
                surname = author.find("tei:surname", TEI_NS)
                parts = []
                if forename is not None and forename.text:
                    parts.append(forename.text.strip())
                if surname is not None and surname.text:
                    parts.append(surname.text.strip())
                if parts:
                    data["authors"].append(" ".join(parts))

            # Year
            date_el = header.find(".//tei:publicationStmt/tei:date[@type='published']", TEI_NS)
            if date_el is not None:
                when = date_el.get("when", "")
                match = re.search(r"\d{4}", when)
                if match:
                    data["year"] = int(match.group())

            # Journal
            journal_el = header.find(".//tei:monogr/tei:title[@level='j']", TEI_NS)
            if journal_el is not None and journal_el.text:
                data["journal"] = journal_el.text.strip()

            # DOI
            doi_el = header.find(".//tei:idno[@type='DOI']", TEI_NS)
            if doi_el is not None and doi_el.text:
                data["doi"] = doi_el.text.strip()

            # Keywords
            for kw in header.findall(".//tei:keywords/tei:term", TEI_NS):
                if kw.text:
                    data["keywords"].append(kw.text.strip())

            # Abstract
            abstract_el = header.find(".//tei:abstract", TEI_NS)
            if abstract_el is not None:
                data["abstract"] = _get_element_text(abstract_el).strip()

        # Sections from body
        if body is not None:
            for order, div in enumerate(body.findall(".//tei:div", TEI_NS)):
                head = div.find("tei:head", TEI_NS)
                section_name = head.text.strip() if head is not None and head.text else f"Section {order + 1}"
                content = _get_element_text(div).strip()

                if not content:
                    continue

                # Detect heading level from @n attribute (e.g., "1", "1.1")
                level = 1
                if head is not None:
                    n = head.get("n", "")
                    level = n.count(".") + 1 if n else 1

                section_type = _infer_section_type(section_name)

                # Track parent section theo level
                parent_name = None
                if level > 1 and data["sections"]:
                    for prev in reversed(data["sections"]):
                        if prev.level < level:
                            parent_name = prev.name
                            break

                data["sections"].append(Section(
                    name=section_name,
                    content=content,
                    order=order,
                    level=level,
                    section_type=section_type,
                    parent_section=parent_name,
                ))

        # References → list[Reference]
        for ref in root.findall(".//tei:listBibl/tei:biblStruct", TEI_NS):
            ref_title = ref.find(".//tei:title[@level='a']", TEI_NS)

            # Extract DOI
            ref_doi_el = ref.find(".//tei:idno[@type='DOI']", TEI_NS)

            # Extract year
            ref_date_el = ref.find(".//tei:date[@type='published']", TEI_NS)
            ref_year = None
            if ref_date_el is not None:
                match = re.search(r"\d{4}", ref_date_el.get("when", ""))
                if match:
                    ref_year = int(match.group())

            # Extract authors
            ref_authors = []
            for author in ref.findall(".//tei:persName", TEI_NS):
                forename = author.find("tei:forename", TEI_NS)
                surname = author.find("tei:surname", TEI_NS)
                parts = []
                if forename is not None and forename.text:
                    parts.append(forename.text.strip())
                if surname is not None and surname.text:
                    parts.append(surname.text.strip())
                if parts:
                    ref_authors.append(" ".join(parts))

            raw_text = ref_title.text.strip() if ref_title is not None and ref_title.text else ""
            if raw_text:
                data["references"].append(Reference(
                    raw_text=raw_text,
                    doi=ref_doi_el.text.strip() if ref_doi_el is not None and ref_doi_el.text else None,
                    title=raw_text,
                    authors=ref_authors,
                    year=ref_year,
                ))

    except ET.ParseError as e:
        logger.error("TEI XML parse error: %s", e)

    return data


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def _merge(pymupdf_data: dict, grobid_data: dict, file_path: str) -> UnifiedDocument:
    """Merge PyMuPDF and GROBID results into UnifiedDocument."""

    now = datetime.now()

    # If GROBID succeeded, use its structure
    if grobid_data.get("success"):
        return UnifiedDocument(
            title=grobid_data["title"],
            authors=grobid_data["authors"],
            year=grobid_data["year"],
            journal=grobid_data["journal"],
            doi=grobid_data["doi"],
            keywords=grobid_data["keywords"],
            abstract=grobid_data["abstract"],
            sections=grobid_data["sections"],
            tables=pymupdf_data["tables"],       # PyMuPDF tables are better
            figures=pymupdf_data["figures"],
            references=grobid_data["references"],
            source_file=file_path,
            source_type="pdf",
            page_count=pymupdf_data["page_count"],
            processing_status="parsed",
            created_at=now,
        )

    # Fallback: GROBID failed — use raw PyMuPDF text as single section
    logger.warning("GROBID unavailable — using PyMuPDF fallback (structure will be limited)")
    raw_text = "\n\n".join(pymupdf_data["raw_text_by_page"])

    return UnifiedDocument(
        title=Path(file_path).stem,   # filename as title
        abstract="",
        sections=[Section(
            name="Full Text",
            content=raw_text,
            order=0,
            level=1,
            section_type="other",
        )],
        tables=pymupdf_data["tables"],
        figures=pymupdf_data["figures"],
        source_file=file_path,
        source_type="pdf",
        page_count=pymupdf_data["page_count"],
        processing_status="parsed",
        created_at=now,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_element_text(element) -> str:
    """Recursively extract all text from an XML element."""
    return " ".join(element.itertext()).strip()


def _infer_section_type(section_name: str) -> Optional[str]:
    """Map section heading to known academic section type.
    Sort by key length descending to avoid partial matches
    (e.g., 'experimental results' should not match 'result' before 'experimental results').
    """
    normalized = section_name.lower().strip()
    for key, section_type in sorted(SECTION_TYPE_MAP.items(), key=lambda x: -len(x[0])):
        if key in normalized:
            return section_type
    return "other"


# ---------------------------------------------------------------------------
# Quick self-test (run: python pdf_loader.py <path_to_pdf>)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s | %(name)s | %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python pdf_loader.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    try:
        doc = load_pdf(pdf_path)
        print(f"\n{'='*50}")
        print(f"Title    : {doc.title}")
        print(f"Authors  : {', '.join(doc.authors)}")
        print(f"Year     : {doc.year}")
        print(f"Journal  : {doc.journal}")
        print(f"DOI      : {doc.doi}")
        print(f"Keywords : {', '.join(doc.keywords)}")
        print(f"Abstract : {doc.abstract[:200]}...")
        print(f"Sections : {len(doc.sections)}")
        for s in doc.sections[:5]:
            print(f"  [{s.order}] L{s.level} [{s.section_type}] {s.name} — {len(s.content)} chars")
            if s.parent_section:
                print(f"    └─ parent: {s.parent_section}")
        print(f"Tables   : {len(doc.tables)}")
        print(f"Figures  : {len(doc.figures)}")
        print(f"Refs     : {len(doc.references)}")
        print(f"Pages    : {doc.page_count}")
        print(f"Status   : {doc.processing_status}")
        print(f"Created  : {doc.created_at}")
        print(f"{'='*50}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
