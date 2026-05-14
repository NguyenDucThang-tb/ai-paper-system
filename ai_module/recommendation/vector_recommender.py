from __future__ import annotations

from ai_module.embedding.embedding_service import EmbeddingService
from ai_module.inference.inference_config import InferenceConfig

from .hybrid_recommender import recommend_papers


class VectorRecommender:
    def __init__(self, config: InferenceConfig) -> None:
        self.embedding = EmbeddingService(config)

    def recommend(self, index_path: str, query: str, top_k: int = 5):
        return recommend_papers(index_path=index_path, embedding_service=self.embedding, query=query, top_k=top_k, mode="hybrid")
