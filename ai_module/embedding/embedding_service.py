from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ai_module.inference.inference_config import InferenceConfig

from .embedding_model import EmbeddingModel


@dataclass
class EmbeddingService:
    config: InferenceConfig

    def __post_init__(self) -> None:
        self.model = EmbeddingModel(self.config)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return self.model.encode_texts(texts)

    def embed_query(self, query: str) -> List[float]:
        return self.model.encode_query(query)

    def embed_documents(self, docs: List[Dict[str, Any]], key: str = "text") -> List[List[float]]:
        return self.embed_texts([str(d.get(key, "")) for d in docs])
