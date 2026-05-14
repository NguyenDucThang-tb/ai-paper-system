from __future__ import annotations

from ai_module.embedding.embedding_service import EmbeddingService
from ai_module.inference.inference_config import InferenceConfig

from .hybrid_recommender import recommend_papers


class MetadataRecommender:
    def __init__(self, config: InferenceConfig) -> None:
        self.embedding = EmbeddingService(config)

    def recommend_by_author(self, index_path: str, author: str, top_k: int = 5):
        return recommend_papers(index_path=index_path, embedding_service=self.embedding, top_k=top_k, author=author, mode="by-author")

    def recommend_by_method(self, index_path: str, method: str, top_k: int = 5):
        return recommend_papers(index_path=index_path, embedding_service=self.embedding, top_k=top_k, method=method, mode="by-method")
