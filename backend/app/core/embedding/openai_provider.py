from typing import List, Optional
import structlog
from app.core.embedding.base import EmbeddingProvider
from app.config import get_settings

logger = structlog.get_logger("rag_enterprise.embedding.openai")


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI API embedding provider (text-embedding-3-small, text-embedding-3-large).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "text-embedding-3-small",
        dimension: int = 1536,
        **kwargs,
    ):
        settings = get_settings()
        self._api_key = api_key or settings.openai_api_key
        self._model_name = model_name
        self._dimension = dimension
        self._client = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return "v3.0"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _get_client(self):
        if self._client is None:
            import openai
            self._client = openai.AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        client = self._get_client()
        res = await client.embeddings.create(
            model=self._model_name,
            input=texts,
            dimensions=self._dimension,
        )
        return [item.embedding for item in res.data]

    async def embed_query(self, query: str) -> List[float]:
        vectors = await self.embed_texts([query])
        return vectors[0]
