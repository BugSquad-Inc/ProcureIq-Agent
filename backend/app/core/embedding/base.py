from abc import ABC, abstractmethod
import math
from typing import List, Optional

_TORCH_BLOCKED_REASON: Optional[str] = None


def mark_torch_unavailable(reason: str) -> None:
    """Cache native torch/DLL load failures once per process to avoid repeated retry stalls."""
    global _TORCH_BLOCKED_REASON
    _TORCH_BLOCKED_REASON = reason


def get_torch_unavailable_reason() -> Optional[str]:
    return _TORCH_BLOCKED_REASON


def align_embedding_dimension(vector: List[float], target_dim: int) -> List[float]:
    """
    Ensure an embedding vector matches `target_dim` (e.g., 2560 for HALFVEC(2560)).
    Tiles or truncates and re-normalizes to unit L2 norm when dimensions differ.
    """
    if len(vector) == target_dim:
        return vector
    if not vector:
        return [0.0] * target_dim
    if len(vector) > target_dim:
        sliced = vector[:target_dim]
    else:
        repeats = (target_dim // len(vector)) + 1
        sliced = (vector * repeats)[:target_dim]
    norm = math.sqrt(sum(v * v for v in sliced)) or 1.0
    return [v / norm for v in sliced]


class EmbeddingProvider(ABC):
    """
    Abstract base class for switchable embedding providers.
    Allows zero-code-change switching between Qwen3, local BGE, Gemini, OpenAI, and Hash.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier name."""
        pass

    @property
    @abstractmethod
    def model_version(self) -> str:
        """Model version tag."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality."""
        pass

    @abstractmethod
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Compute dense vector representations for a batch of texts."""
        pass

    @abstractmethod
    async def embed_query(self, query: str) -> List[float]:
        """Compute dense vector representation for a search query."""
        pass
