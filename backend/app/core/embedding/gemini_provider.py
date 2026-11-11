"""
gemini_provider.py — Pure-HTTP Google Gemini Embedding provider (zero PyTorch dependency).
"""
from typing import List, Optional
import httpx
import structlog

from app.config import get_settings
from app.core.embedding.base import EmbeddingProvider, align_embedding_dimension
from app.core.embedding.hash_provider import HashEmbeddingProvider

logger = structlog.get_logger("procureiq.embedding.gemini")


class GeminiEmbeddingProvider(EmbeddingProvider):
    """REST-based Gemini embedding provider using httpx (no native DLL dependencies)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        dimension: int = 2560,
        **kwargs,
    ):
        settings = get_settings()
        self._api_key = (api_key or settings.gemini_api_key or "").strip()
        self._model_name = model_name or settings.gemini_embedding_model
        self._dimension = dimension
        self._verify_ssl = settings.gemini_verify_ssl
        self._fallback = HashEmbeddingProvider(dimension=384)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return "v1"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if not self._api_key:
            logger.warning("gemini_embedding_no_api_key_using_hash_fallback")
            vecs = await self._fallback.embed_texts(texts)
            return [align_embedding_dimension(v, self._dimension) for v in vecs]

        model = self._model_name.replace("models/", "")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:batchEmbedContents?key={self._api_key}"
        )
        requests_payload = [
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": t}]},
                "outputDimensionality": min(self._dimension, 3072),
            }
            for t in texts
        ]
        try:
            async with httpx.AsyncClient(verify=self._verify_ssl, timeout=15.0) as client:
                resp = await client.post(url, json={"requests": requests_payload})
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = [
                        align_embedding_dimension(item["values"], self._dimension)
                        for item in data.get("embeddings", [])
                    ]
                    if len(embeddings) == len(texts):
                        return embeddings
                logger.warning("gemini_embedding_http_error", status=resp.status_code)
        except Exception as exc:
            logger.warning("gemini_embedding_failed_using_fallback", error=str(exc))

        vecs = await self._fallback.embed_texts(texts)
        return [align_embedding_dimension(v, self._dimension) for v in vecs]

    async def embed_query(self, query: str) -> List[float]:
        vectors = await self.embed_texts([query])
        return vectors[0]

