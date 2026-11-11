"""
resilience.py — Production Circuit Breaker & Exponential Backoff Retry utilities.

Protects external API adapters (PayPal, ERP, LLM services) from cascading
failures when downstream endpoints experience rate limits (429) or outages (5xx).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, TypeVar

import structlog

logger = structlog.get_logger("procureiq.resilience")

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised immediately when a service's circuit breaker is OPEN."""

    def __init__(self, service: str, retry_after_sec: float):
        self.service = service
        self.retry_after_sec = round(retry_after_sec, 2)
        super().__init__(
            f"Service '{service}' circuit breaker is OPEN. Retry in {self.retry_after_sec}s."
        )


@dataclass
class CircuitBreaker:
    service: str
    failure_threshold: int = 3
    recovery_timeout_sec: float = 30.0
    state: str = "closed"          # "closed" | "open" | "half_open"
    failure_count: int = 0
    last_failure_ts: float = 0.0
    total_successes: int = 0
    total_failures: int = 0
    _half_open_probe_in_flight: bool = field(default=False, repr=False)

    def allow_request(self) -> None:
        if self.state == "closed":
            return
        elapsed = time.monotonic() - self.last_failure_ts
        if self.state == "open":
            if elapsed >= self.recovery_timeout_sec:
                self.state = "half_open"
                self._half_open_probe_in_flight = True
                logger.info("circuit_half_open", service=self.service)
                return
            raise CircuitOpenError(self.service, self.recovery_timeout_sec - elapsed)
        # half_open: allow single probe
        if self._half_open_probe_in_flight:
            raise CircuitOpenError(self.service, 1.0)
        self._half_open_probe_in_flight = True

    def record_success(self) -> None:
        self.total_successes += 1
        self.failure_count = 0
        self._half_open_probe_in_flight = False
        if self.state != "closed":
            logger.info("circuit_closed", service=self.service, prev_state=self.state)
            self.state = "closed"

    def record_failure(self) -> None:
        self.total_failures += 1
        self.failure_count += 1
        self.last_failure_ts = time.monotonic()
        self._half_open_probe_in_flight = False
        if self.state == "half_open" or self.failure_count >= self.failure_threshold:
            if self.state != "open":
                logger.warning(
                    "circuit_opened",
                    service=self.service,
                    failures=self.failure_count,
                    recovery_timeout_sec=self.recovery_timeout_sec,
                )
            self.state = "open"

    def status_dict(self) -> Dict[str, Any]:
        retry_after = 0.0
        if self.state == "open":
            retry_after = max(0.0, self.recovery_timeout_sec - (time.monotonic() - self.last_failure_ts))
        return {
            "service": self.service,
            "state": self.state,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_sec": self.recovery_timeout_sec,
            "retry_after_sec": round(retry_after, 2),
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
        }


class CircuitBreakerRegistry:
    """Thread-safe registry of per-service circuit breakers."""

    _breakers: Dict[str, CircuitBreaker] = {}

    @classmethod
    def get(
        cls,
        service: str,
        failure_threshold: int = 3,
        recovery_timeout_sec: float = 30.0,
    ) -> CircuitBreaker:
        if service not in cls._breakers:
            cls._breakers[service] = CircuitBreaker(
                service=service,
                failure_threshold=failure_threshold,
                recovery_timeout_sec=recovery_timeout_sec,
            )
        return cls._breakers[service]

    @classmethod
    def all_statuses(cls) -> Dict[str, Dict[str, Any]]:
        return {name: cb.status_dict() for name, cb in cls._breakers.items()}

    @classmethod
    def reset_all(cls) -> None:
        for cb in cls._breakers.values():
            cb.state = "closed"
            cb.failure_count = 0
            cb._half_open_probe_in_flight = False


async def run_with_resilience(
    service_name: str,
    fn: Callable[[], Awaitable[T]],
    max_attempts: int = 2,
    base_delay_sec: float = 0.15,
) -> T:
    """
    Execute an async operation guarded by a CircuitBreaker and exponential backoff.
    """
    breaker = CircuitBreakerRegistry.get(service_name)
    breaker.allow_request()

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = await fn()
            breaker.record_success()
            return result
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "resilient_call_attempt_failed",
                service=service_name,
                attempt=attempt,
                max_attempts=max_attempts,
                error=str(exc),
            )
            if attempt < max_attempts:
                await asyncio.sleep(base_delay_sec * (2 ** (attempt - 1)))

    breaker.record_failure()
    raise last_exc  # type: ignore[misc]

