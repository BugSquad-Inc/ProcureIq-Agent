from typing import List, Optional
import asyncio
import structlog
from app.core.embedding.base import (
    EmbeddingProvider,
    get_torch_unavailable_reason,
    mark_torch_unavailable,
)
from app.config import get_settings
from app.core.embedding.hash_provider import HashEmbeddingProvider

logger = structlog.get_logger("procureiq.embedding.local_st")


class LocalSentenceTransformerProvider(EmbeddingProvider):
    """
    Local CPU/CUDA SentenceTransformer provider.
    Default model: BAAI/bge-base-en-v1.5 (768 dimensions).
    Falls back cleanly to HashEmbeddingProvider if sentence-transformers / torch
    cannot load (e.g., Windows Application Control blocking torch.dll).
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        batch_size: Optional[int] = None,
        **kwargs,
    ):
        settings = get_settings()
        self._model_name = model_name or settings.local_embedding_model
        self._dimension = settings.local_embedding_dimension
        self._device = device
        self._batch_size = batch_size
        self._model = None
        self._offline_fallback: Optional[HashEmbeddingProvider] = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return "v1.5"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _activate_hash_fallback(self, reason: str) -> None:
        logger.warning("local_models_unavailable_using_hash_embeddings", error=reason)
        self._offline_fallback = HashEmbeddingProvider()
        self._model_name = self._offline_fallback.model_name
        self._dimension = self._offline_fallback.dimension

    def _get_model(self):
        if self._model is None and self._offline_fallback is None:
            settings = get_settings()
            if not settings.enable_local_models:
                self._activate_hash_fallback("enable_local_models=False")
                return None

            blocked_reason = get_torch_unavailable_reason()
            if blocked_reason:
                self._activate_hash_fallback(blocked_reason)
                return None

            # Catch ALL exceptions (including OSError WinError 4551 when torch.dll
            # is blocked by Windows Application Control) so startup/retrieval never crashes.
            try:
                from sentence_transformers import SentenceTransformer
            except Exception as exc:
                if isinstance(exc, OSError):
                    mark_torch_unavailable(str(exc))
                self._activate_hash_fallback(str(exc))
                return None

            logger.info("loading_sentence_transformer", model=self._model_name)
            local_only = not settings.allow_model_downloads
            try:
                self._model = SentenceTransformer(
                    self._model_name,
                    local_files_only=local_only,
                    trust_remote_code=True,
                )
            except Exception as e:
                logger.warning("failed_loading_bge_falling_back_to_minilm", error=str(e))
                try:
                    self._model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=local_only)
                    self._model_name = "all-MiniLM-L6-v2"
                    self._dimension = 384
                except Exception as fallback_error:
                    self._activate_hash_fallback(str(fallback_error))
        return self._model

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        loop = asyncio.get_running_loop()
        model = self._get_model()
        if self._offline_fallback is not None:
            return await self._offline_fallback.embed_texts(texts)
        embeddings = await loop.run_in_executor(
            None,
            lambda: model.encode(texts, normalize_embeddings=True, show_progress_bar=False),
        )
        return embeddings.tolist()

    async def embed_query(self, query: str) -> List[float]:
        prefix = "Represent this sentence for searching relevant passages: "
        prefixed_query = f"{prefix}{query}" if "bge" in self._model_name.lower() else query
        vectors = await self.embed_texts([prefixed_query])
        return vectors[0]
