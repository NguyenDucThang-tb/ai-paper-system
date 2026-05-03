from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from typing import Any

@dataclass
class Section:
    name: str
    content: str
    order: int
    level: int = 1
    section_type: Optional[str] = None
    parent_section: Optional[str] = None  # tên section cha
    subsections: list["Section"] = field(default_factory=list)

@dataclass
class Table:
    caption: str = ""
    index: Optional[int] = None
    headers: list[str] = field(default_factory=list)
    data: list[list[Any]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)  # thêm vào
    

@dataclass
class Figure:
    caption: str = ""
    index: Optional[int] = None
    path: Optional[str] = None
    base64_data: Optional[str] = None    # thêm vào
    figure_type: str = "image"  # image | chart | diagram
    alt_text: Optional[str] = None
    keywords: list[str] = field(default_factory=list)  # cho KG

@dataclass
class Formula:
    raw: str
    formula_type: str = "inline"      # inline | block | equation
    index: Optional[int] = None
    display_text: Optional[str] = None   # ← THÊM VÀO
    source_format: str = "unknown"   # thêm vào

@dataclass
class Reference:
    raw_text: str
    doi: Optional[str] = None
    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None

@dataclass
class UnifiedDocument:
    # Bibliographic
    title: str = "Unknown"
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    keywords: list[str] = field(default_factory=list)

    # Content
    abstract: str = ""
    sections: list[Section] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    formulas: list[Formula] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)

    # Source info
    source_file: str = ""
    source_type: str = ""  # pdf | docx | html
    language: Optional[str] = None
    page_count: Optional[int] = None

    processing_status: str = "raw"        # raw | parsed | chunked
    errors: list[str] = field(default_factory=list)  # log lỗi từng stage
    created_at: Optional[datetime] = None
    chunk_ids: list[str] = field(default_factory=list)

    publisher: Optional[str] = None
    volume:    Optional[str] = None
    issue:     Optional[str] = None
    pages:     Optional[str] = None
    citation_count: Optional[int] = None
