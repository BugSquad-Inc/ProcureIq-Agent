"""
factory.py — EmbeddingProviderFactory for ProcureIQ.

Default provider: Qwen3-Embedding-4B (2560d) — same model as RAG-Entreprise.
Fallback chain: qwen → local (BGE-768) → hash (offline, zero-dep)

The provider is selected via EMBEDDING_PROVIDER in .env — no code changes needed
to switch models.
"""
from typing import Dict, Optional, Type
import structlog

from app.config import get_settings
from app.core.embedding.base import EmbeddingProvider
from app.core.embedding.qwen_provider import QwenEmbeddingProvider
from app.core.embedding.local_st import LocalSentenceTransformerProvider
from app.core.embedding.gemini_provider import GeminiEmbeddingProvider
from app.core.embedding.openai_provider import OpenAIEmbeddingProvider
from app.core.embedding.hash_provider import HashEmbeddingProvider

logger = structlog.get_logger("procureiq.embedding.factory")


class EmbeddingProviderFactory:
    _providers: Dict[str, Type[EmbeddingProvider]] = {
        "qwen": QwenEmbeddingProvider,               # 2560d — Qwen3-Embedding-4B (default)
        "local": LocalSentenceTransformerProvider,   # 768d  — BAAI/bge-base-en-v1.5
        "gemini": GeminiEmbeddingProvider,           # 2560d — REST Gemini embeddings
        "openai": OpenAIEmbeddingProvider,           # 1536d — text-embedding-3-small
        "hash": HashEmbeddingProvider,               # 384d  — offline fallback, zero deps
    }
    _cache: Dict[str, EmbeddingProvider] = {}

    @classmethod
    def get_provider(cls, provider_name: Optional[str] = None) -> EmbeddingProvider:
        settings = get_settings()
        name = (provider_name or settings.embedding_provider).lower()
        if name not in cls._cache:
            provider_cls = cls._providers.get(name)
            if provider_cls is None:
                logger.warning("unknown_embedding_provider_falling_back", provider=name)
                provider_cls = QwenEmbeddingProvider
            cls._cache[name] = provider_cls()
            logger.info(
                "embedding_provider_loaded",
                provider=name,
                model=cls._cache[name].model_name,
                dimension=cls._cache[name].dimension,
            )
        return cls._cache[name]

    @classmethod
    def reset_cache(cls) -> None:
        """Clear cached provider instances (useful for tests)."""
        cls._cache.clear()
