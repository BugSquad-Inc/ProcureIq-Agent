import asyncio
from dataclasses import dataclass
import re
from typing import List, Optional, Tuple
import structlog
from app.core.embedding.base import get_torch_unavailable_reason, mark_torch_unavailable
from app.core.hybrid_search import SearchCandidate
from app.config import get_settings

logger = structlog.get_logger("rag_enterprise.reranking")


def compute_intent_multiplier(query_text: str, candidate_text: str) -> float:
    """
    Safety multiplier preventing destructive/mutating tools (`cancel_*`, `send_*`, `create_*`)
    from outranking read/lookup tools when the user asks a pure read/status query
    (e.g., "get me the mike invoice already sent").
    """
    from app.core.hybrid_search import normalize_query_text

    norm_q = normalize_query_text(query_text).lower()
    cand_low = candidate_text.lower()

    has_cancel = bool(re.search(r"\b(cancel|void|abort|delete|revoke|terminate)\b", norm_q))
    if not has_cancel and re.search(r"\b(cancel|void|abort|delete|revoke|terminate)\b", cand_low):
        return 0.55

    has_lookup = bool(
        re.search(
            r"\b(get|fetch|check|find|retrieve|show|view|already sent|was sent|status|details|is there)\b",
            norm_q,
        )
    )
    has_send_or_create = bool(
        re.search(
            r"(?<!already\s)(?<!was\s)\b(send|email|deliver|dispatch|mail|remind|create|draft|issue|generate)\b",
            norm_q,
        )
    )
    if has_lookup and not has_send_or_create and re.search(r"\b(send|remind|create)\b", cand_low):
        return 0.65

    return 1.0


def lexical_alignment_score(text_a: str, text_b: str) -> float:
    """Fast no-model alignment score with explainable domain concept aliases."""
    import re
    from app.core.hybrid_search import normalize_query_text

    norm_a = normalize_query_text(text_a)
    norm_b = normalize_query_text(text_b)
    words_a = set(re.findall(r"[a-z0-9]+", norm_a.lower()))
    words_b = set(re.findall(r"[a-z0-9]+", norm_b.lower()))
    if not words_a or not words_b:
        return 0.0
    jaccard = len(words_a & words_b) / len(words_a | words_b)
    containment = len(words_a & words_b) / min(len(words_a), len(words_b))
    word_score = 0.45 * jaccard + 0.55 * containment

    # Normalize common enterprise paraphrases without pretending that this is
    # a general semantic model. A boost requires at least two shared concepts,
    # which protects unrelated clauses that happen to share one generic word.
    concept_patterns = {
        "party_provider": r"\b(vendor|supplier|provider|hosting partner|receiving party|recipient)\b",
        "transport": r"\b(transportation|shipping|freight|cargo|transit|dispatch)\b",
        "cost": r"\b(costs?|expenses?|fees?)\b",
        "insurance": r"\b(insurance|coverage)\b",
        "delivery": r"\b(delivery|deliver|dispatch|shipment)\b",
        "confidentiality": r"\b(confidential|not disclose|non-public|protect)\b",
        "proprietary": r"\b(proprietary|trade secrets?|know-how)\b",
        "business_material": r"\b(business plans?|business strategies?)\b",
        "technical_material": r"\b(technical architectures?|technical blueprints?)\b",
        "availability": r"\b(availability|uptime|operates?|operational)\b",
        "online_system": r"\b(system|cloud service|online infrastructure|hosting)\b",
        "minimum_commitment": r"\b(not less than|minimum|guarantees?|shall maintain)\b",
        # Procurement / Payment / FinTech tool alignment concepts
        "invoicing": r"\b(invoices?|bills?|billing|receipts?|statements?)\b",
        "payment_action": r"\b(pay|payments?|transfer|wire|payouts?|disburse)\b",
        "send_action": r"\b(?<!already\s)(?<!was\s)\b(send|email|deliver|dispatch|mail)\b",
        "cancel_action": r"\b(cancel|void|abort|delete|revoke|terminate)\b",
        "disputes": r"\b(disputes?|chargebacks?|claims?|refunds?|complaints?|escalate)\b",
        "analytics": r"\b(sales|revenue|spend|total|volume|report|analytics|summary|breakdown)\b",
        "purchase_order": r"\b(purchase orders?|pos?|requisitions?|procure|rfq|quotes?)\b",
        "creation": r"\b(create|new|draft|issue|generate|place|register|submit)\b",
        "lookup": r"\b(get|fetch|check|find|retrieve|status|details|view|track|already sent|is there)\b",
        "listing": r"\b(list|all|show|history|recent|search|filter)\b",
    }

    lowered_a, lowered_b = norm_a.lower(), norm_b.lower()
    concepts_a = {name for name, pattern in concept_patterns.items() if re.search(pattern, lowered_a)}
    concepts_b = {name for name, pattern in concept_patterns.items() if re.search(pattern, lowered_b)}
    shared_concepts = concepts_a & concepts_b
    concept_score = 0.0
    if len(shared_concepts) >= 2:
        concept_containment = len(shared_concepts) / min(len(concepts_a), len(concepts_b))
        concept_jaccard = len(shared_concepts) / len(concepts_a | concepts_b)
        concept_score = 0.62 * concept_containment + 0.38 * concept_jaccard

    score = min(1.0, max(word_score, concept_score)) * compute_intent_multiplier(text_a, text_b)
    return round(score, 4)


@dataclass
class RerankResult:
    candidate: SearchCandidate
    reranker_score: float


class CrossEncoderReranker:
    """
    Level 4 Cross-Encoder Reranker.
    Computes cross-attention alignment between query text and candidate chunks.
    Transforms bi-encoder candidate retrieval into precision ranking.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            if not get_settings().enable_local_models or get_torch_unavailable_reason():
                logger.info("cross_encoder_disabled_using_lexical_reranking")
                self._model = False
                return self._model
            logger.info("loading_cross_encoder_model", model=self.model_name)
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(
                    self.model_name,
                    max_length=512,
                    local_files_only=not get_settings().allow_model_downloads,
                )
            except Exception as e:
                if isinstance(e, OSError):
                    mark_torch_unavailable(str(e))
                logger.warning("cross_encoder_unavailable_using_lexical_fallback", error=str(e))
                self._model = False
        return self._model

    async def rerank(
        self,
        query_text: str,
        candidates: List[SearchCandidate],
        top_k: int = 10,
    ) -> List[RerankResult]:
        if not candidates:
            return []

        pairs = [(query_text, cand.text) for cand in candidates]
        loop = asyncio.get_running_loop()
        model = self._get_model()
        if model is False:
            results = [
                RerankResult(candidate=cand, reranker_score=lexical_alignment_score(query_text, cand.text))
                for cand in candidates
            ]
            results.sort(key=lambda result: result.reranker_score, reverse=True)
            return results[:top_k]

        # Run cross-encoder in thread executor
        raw_scores = await loop.run_in_executor(
            None,
            lambda: model.predict(pairs, show_progress_bar=False),
        )

        results: List[RerankResult] = []
        for cand, score in zip(candidates, raw_scores):
            # Sigmoid normalization if scores are raw logits
            val = float(score)
            if val < 0 or val > 1:
                import math
                norm_score = 1.0 / (1.0 + math.exp(-val))
            else:
                norm_score = val

            norm_score *= compute_intent_multiplier(query_text, cand.text)
            results.append(
                RerankResult(
                    candidate=cand,
                    reranker_score=round(norm_score, 4),
                )
            )

        results.sort(key=lambda r: r.reranker_score, reverse=True)
        return results[:top_k]

    def predict_score(self, query_text: str, candidate_text: str) -> float:
        """Synchronously predict cross-attention score for a single pair."""
        model = self._get_model()
        if model is False:
            return lexical_alignment_score(query_text, candidate_text)
        score = model.predict([(query_text, candidate_text)], show_progress_bar=False)[0]
        val = float(score)
        if val < 0 or val > 1:
            import math
            return round(1.0 / (1.0 + math.exp(-val)), 4)
        return round(val, 4)


_reranker_instance: Optional[CrossEncoderReranker] = None


def get_cross_encoder_reranker() -> CrossEncoderReranker:
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = CrossEncoderReranker()
    return _reranker_instance
