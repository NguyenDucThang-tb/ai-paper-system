from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

import torch
from sentence_transformers import SentenceTransformer

from ai_module.inference.inference_config import InferenceConfig

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingModel:
    config: InferenceConfig

    def __post_init__(self) -> None:
        self.model_name = self.config.embedding_model_name
        self.model = self._load_with_fallback(self.model_name)

    def _load_with_fallback(self, model_name: str) -> SentenceTransformer:
        candidates = [model_name]
        if self.config.embedding_fallback_model_name not in candidates:
            candidates.append(self.config.embedding_fallback_model_name)

        last_error = None
        for cand in candidates:
            devices = []
            if self.config.device == "cuda" and torch.cuda.is_available():
                devices.append("cuda")
            devices.append("cpu")
            for dev in devices:
                try:
                    logger.info("Loading embedding %s on %s", cand, dev)
                    self.model_name = cand
                    return SentenceTransformer(cand, device=dev)
                except Exception as ex:
                    last_error = ex
                    logger.warning("Embedding load failed %s on %s: %s", cand, dev, ex)

        raise RuntimeError(f"Failed to load embedding model from {candidates}: {last_error}")

    def encode_texts(self, texts: List[str]) -> List[List[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True, batch_size=16, show_progress_bar=False)
        return vectors.tolist()

    def encode_query(self, query: str) -> List[float]:
        vectors = self.model.encode([query], normalize_embeddings=True, show_progress_bar=False)
        return vectors[0].tolist()
