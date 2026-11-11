import asyncio
import os
import threading
from typing import List, Optional

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
        self._use_http_first = bool(getattr(settings, "qwen_use_http_first", False))
        self._device = device
        self._batch_size = batch_size
        self._fallback_provider = None
        self._active_backend = "qwen-http"
        self._http_available: Optional[bool] = None
        self._local_model = None
        self._local_model_checked = False
        self._query_cache: dict[str, List[float]] = {}
        self._infer_lock = threading.Lock()

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

        settings = get_settings()
        if not settings.enable_local_models or get_torch_unavailable_reason():
            return None

        try:
            import json
            from pathlib import Path
            import torch
            from huggingface_hub import try_to_load_from_cache
            from transformers import AutoModel, AutoTokenizer

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
            if not (is_cached or settings.allow_model_downloads):
                return None

            local_only = True if is_ready else not settings.allow_model_downloads
            use_cuda = torch.cuda.is_available()
            device = "cuda" if use_cuda else "cpu"

            logger.info("loading_qwen_local_transformers", model=model_target, device=device)
            tokenizer = AutoTokenizer.from_pretrained(
                model_target,
                padding_side="left",
                local_files_only=local_only,
            )
            load_kwargs = {"local_files_only": local_only}
            if use_cuda:
                load_kwargs.update(
                    {
                        "dtype": torch.float16,
                        "device_map": "auto",
                        "max_memory": {0: "6800MiB", "cpu": "16GiB"},
                    }
                )
            model = AutoModel.from_pretrained(model_target, **load_kwargs)
            model.eval()
            self._local_model = (tokenizer, model)
            self._active_backend = f"local-{device}"
            logger.info(
                "qwen_local_model_ready",
                model=self._model_name,
                backend=self._active_backend,
            )
            return self._local_model
        except Exception as e:
            logger.warning("local_qwen_load_failed", error=str(e))
            if isinstance(e, OSError):
                mark_torch_unavailable(str(e))
            self._local_model = None

        return None

    @staticmethod
    def _last_token_pool(last_hidden_states, attention_mask):
        import torch

        left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
        if left_padding:
            return last_hidden_states[:, -1]
        seq_lens = attention_mask.sum(dim=1) - 1
        batch_size = last_hidden_states.shape[0]
        return last_hidden_states[
            torch.arange(batch_size, device=last_hidden_states.device),
            seq_lens,
        ]

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

    async def _try_http_embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Attempt shared HTTP embedding endpoint (vLLM / Ollama / TEI)."""
        if self._http_available is False:
            return None
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.post(
                    f"{self._base_url}/v1/embeddings",
                    json={"input": texts, "model": self._model_name},
                )
                if res.status_code == 200:
                    self._http_available = True
                    self._active_backend = "qwen-http"
                    data = res.json()
                    embeddings = [item["embedding"] for item in data["data"]]
                    logger.debug("qwen_embedded_via_http", count=len(embeddings))
                    return [align_embedding_dimension(e, self._dimension) for e in embeddings]
                self._http_available = False
        except Exception:
            self._http_available = False
        return None

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        # 0. When shared GPU embedding server is preferred (multi-worker production), try HTTP first
        if self._use_http_first:
            http_embs = await self._try_http_embed(texts)
            if http_embs is not None:
                return http_embs

        # 1. Attempt native local Transformers Qwen3-Embedding-4B execution on GPU
        local_bundle = self._get_local_model()
        if local_bundle is not None:
            try:
                import torch
                import torch.nn.functional as F

                if get_settings().environment.lower() == "production" and not self._use_http_first:
                    logger.warning(
                        "qwen_in_process_production_vram",
                        tip="Set QWEN_USE_HTTP_FIRST=true with a shared embedding server if using multiple Uvicorn workers.",
                    )

                tokenizer, hf_model = local_bundle
                loop = asyncio.get_running_loop()
                batch_size = self._batch_size or 8

                def _encode_slice(chunk: List[str]) -> List[List[float]]:
                    encoded = tokenizer(
                        chunk,
                        padding=True,
                        truncation=True,
                        max_length=512,
                        return_tensors="pt",
                    )
                    input_dev = next(hf_model.parameters()).device
                    encoded = {k: v.to(input_dev) for k, v in encoded.items()}
                    with torch.no_grad():
                        out = hf_model(**encoded)
                        pooled = self._last_token_pool(
                            out.last_hidden_state, encoded["attention_mask"]
                        )
                        normed = F.normalize(pooled, p=2, dim=1)
                        return normed.cpu().float().tolist()

                def _encode_batched():
                    all_embs: List[List[float]] = []
                    with self._infer_lock:
                        for i in range(0, len(texts), batch_size):
                            batch = texts[i : i + batch_size]
                            try:
                                all_embs.extend(_encode_slice(batch))
                            except Exception as oom_err:
                                if torch.cuda.is_available():
                                    torch.cuda.empty_cache()
                                logger.warning("qwen_batch_oom_retrying_single", error=str(oom_err))
                                for item in batch:
                                    all_embs.extend(_encode_slice([item]))
                                    if torch.cuda.is_available():
                                        torch.cuda.empty_cache()
                    return all_embs

                embeddings = await loop.run_in_executor(None, _encode_batched)
                return [align_embedding_dimension(emb, self._dimension) for emb in embeddings]
            except Exception as e:
                logger.warning("local_qwen_inference_failed_falling_back", error=str(e))

        # 2. Attempt HTTP inference endpoint (vLLM / Ollama) if not already tried first
        if not self._use_http_first:
            http_embs = await self._try_http_embed(texts)
            if http_embs is not None:
                return http_embs

        # 3. Local execution fallback: Generate dense representations and project to target 2560 dim
        logger.debug("using_local_st_with_dimension_mapping_for_qwen")
        fallback = self._get_fallback()
        base_embeddings = await fallback.embed_texts(texts)

        target_dim = self._dimension
        return [align_embedding_dimension(emb, target_dim) for emb in base_embeddings]

    async def embed_query(self, query: str) -> List[float]:
        cached = self._query_cache.get(query)
        if cached is not None:
            return cached
        prompted = (
            f"Instruct: Given a web search query, retrieve relevant passages that answer the query\n"
            f"Query:{query}"
        )
        vectors = await self.embed_texts([prompted])
        if len(self._query_cache) >= 256:
            self._query_cache.clear()
        self._query_cache[query] = vectors[0]
        return vectors[0]
