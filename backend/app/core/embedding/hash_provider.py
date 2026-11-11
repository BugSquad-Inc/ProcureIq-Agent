import hashlib
import math
import re
from typing import List, Tuple

from app.core.embedding.base import EmbeddingProvider

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "for",
    "of", "in", "on", "at", "by", "with", "from", "and", "or", "my", "our",
    "me", "i", "you", "there", "this", "that", "what", "how", "can", "do",
}


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic offline embedding fallback based on weighted feature hashing.

    Combines word unigrams, word bigrams, and character 4-grams so morphological
    variants (e.g., invoice/invoicing, dispute/disputes, payment/pay) share dense
    similarity without requiring native PyTorch binaries.
    """

    def __init__(self, dimension: int = 384, **kwargs):
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return "offline-feature-hash"

    @property
    def model_version(self) -> str:
        return "v2"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _extract_weighted_features(self, text: str) -> List[Tuple[str, float]]:
        normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
        raw_tokens = [t for t in normalized.split() if t]
        tokens = [t for t in raw_tokens if t not in _STOPWORDS] or raw_tokens

        features: List[Tuple[str, float]] = []
        for tok in tokens:
            features.append((f"w:{tok}", 2.0))
            if len(tok) >= 4:
                features.append((f"p4:{tok[:4]}", 1.2))
            if len(tok) >= 4:
                for i in range(len(tok) - 3):
                    features.append((f"c4:{tok[i:i+4]}", 0.45))

        for a, b in zip(tokens, tokens[1:]):
            features.append((f"bi:{a}_{b}", 1.5))
        return features

    def _embed(self, text: str) -> List[float]:
        vector = [0.0] * self._dimension
        for feature, weight in self._extract_weighted_features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self._dimension
            sign = -1.0 if (value & 1) else 1.0
            vector[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, query: str) -> List[float]:
        return self._embed(query)
