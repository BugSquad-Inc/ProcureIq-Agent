import os
from typing import List, Optional
import asyncio
import httpx
import structlog
from app.core.embedding.base import (
    EmbeddingProvider,
    align_embedding_dimension,
    get_torch_unavailable_reason,
    mark_torch_unavailable,
)
from app.core.embedding.local_st import LocalSentenceTransformerProvider
from app.core.embedding.hash_provider import HashEmbeddingProvider
from app.config import get_settings

logger = structlog.get_logger("procureiq.embedding.qwen")


class QwenEmbeddingProvider(EmbeddingProvider):
    """
    Qwen3-Embedding-4B provider.
    Dimensions: 2560.
    Supports:
    1. HTTP OpenAI-compatible endpoint (vLLM / Ollama / TEI).
    2. Local HuggingFace / SentenceTransformers execution.
    3. Seamless local fallback if self-hosted inference server is offline.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        dimension: int = 2560,
        device: Optional[str] = None,
        batch_size: Optional[int] = None,
        **kwargs,
    ):
        settings = get_settings()
        self._model_name = model_name or settings.embedding_model
        self._dimension = dimension or settings.embedding_dimension
        self._base_url = base_url or os.getenv("QWEN_BASE_URL") or getattr(settings, "qwen_base_url", "http://localhost:11434")
        self._device = device
        self._batch_size = batch_size
        self._fallback_provider = None
        self._active_backend = "qwen-http"
        self._http_available: Optional[bool] = None
        self._local_model = None
        self._local_model_checked = False

    @property
    def model_name(self) -> str:
        if self._active_backend == "qwen-http":
            return self._model_name
        return f"{self._model_name} ({self._active_backend})"

    @property
    def model_version(self) -> str:
        return "v1.0" if self._active_backend == "qwen-http" else f"v1.0+{self._active_backend}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _get_local_model(self):
        if self._local_model_checked:
            return self._local_model
        self._local_model_checked = True

        if get_torch_unavailable_reason():
            return None

        settings = get_settings()
        try:
            import torch
            from sentence_transformers import SentenceTransformer
            import json
            from pathlib import Path
            from huggingface_hub import try_to_load_from_cache

            # Check if verified stamp exists or model is cached
            stamp_path = Path.home() / ".cache" / "huggingface" / "qwen3_4b_ready.json"
            model_target = self._model_name
            is_ready = False

            if stamp_path.exists():
                try:
                    with open(stamp_path, "r", encoding="utf-8") as sf:
                        sdata = json.load(sf)
                        sdir = sdata.get("snapshot_dir")
                        if sdir and os.path.exists(sdir):
                            model_target = sdir
                            is_ready = True
                except Exception:
                    pass

            is_cached = is_ready or (try_to_load_from_cache(self._model_name, "config.json") is not None)
            if is_cached or settings.allow_model_downloads:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                model_kwargs = {}
                if torch.cuda.is_available():
                    try:
                        from transformers import BitsAndBytesConfig
                        bnb_cfg = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
                        model_kwargs = {"quantization_config": bnb_cfg, "device_map": "auto"}
                    except Exception:
                        model_kwargs = {"torch_dtype": torch.float16}

                logger.info("loading_qwen_local_sentence_transformer", model=model_target, device=device)
                self._local_model = SentenceTransformer(
                    model_target,
                    model_kwargs=model_kwargs,
                    device=device if "device_map" not in model_kwargs else None,
                    local_files_only=True if is_ready else not settings.allow_model_downloads
                )
                self._active_backend = f"local-{device}"
                return self._local_model
        except Exception as e:
            logger.warning("local_qwen_load_failed", error=str(e))
            if isinstance(e, OSError):
                mark_torch_unavailable(str(e))
            self._local_model = None

        return None

    def _get_fallback(self):
        if self._fallback_provider is None:
            settings = get_settings()
            self._fallback_provider = (
                LocalSentenceTransformerProvider()
                if settings.enable_local_models
                else HashEmbeddingProvider()
            )
            self._active_backend = (
                "local-semantic-fallback"
                if settings.enable_local_models
                else "offline-hash-fallback"
            )
        return self._fallback_provider

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        # 1. Attempt native local SentenceTransformer execution on GPU
        local_model = self._get_local_model()
        if local_model is not None:
            try:
                loop = asyncio.get_running_loop()
                batch_size = self._batch_size or 16

                def _encode_batched():
                    all_embs = []
                    for i in range(0, len(texts), batch_size):
                        batch = texts[i : i + batch_size]
                        try:
                            embs = local_model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
                            all_embs.extend(embs.tolist())
                        except Exception as oom_err:
                            import torch
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                            logger.warning("qwen_batch_oom_retrying_single", error=str(oom_err))
                            for item in batch:
                                embs_single = local_model.encode([item], normalize_embeddings=True, show_progress_bar=False)
                                all_embs.extend(embs_single.tolist())
                                if torch.cuda.is_available():
                                    torch.cuda.empty_cache()
                    return all_embs

                embeddings = await loop.run_in_executor(None, _encode_batched)
                return embeddings
            except Exception as e:
                logger.warning("local_qwen_inference_failed_falling_back", error=str(e))

        # 2. Attempt HTTP inference endpoint (vLLM / Ollama)
        if self._http_available is not False:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.post(
                        f"{self._base_url}/v1/embeddings",
                        json={"input": texts, "model": self._model_name},
                    )
                    if res.status_code == 200:
                        self._http_available = True
                        data = res.json()
                        embeddings = [item["embedding"] for item in data["data"]]
                        logger.debug("qwen_embedded_via_http", count=len(embeddings))
                        return embeddings
                    self._http_available = False
            except Exception:
                # Circuit-break for this provider instance.
                self._http_available = False

        # 3. Local execution fallback: Generate dense representations and project to target 2560 dim
        logger.debug("using_local_st_with_dimension_mapping_for_qwen")
        fallback = self._get_fallback()
        base_embeddings = await fallback.embed_texts(texts)

        target_dim = self._dimension
        return [align_embedding_dimension(emb, target_dim) for emb in base_embeddings]

    async def embed_query(self, query: str) -> List[float]:
        vectors = await self.embed_texts([query])
        return vectors[0]
