"""
config.py — ProcureIQ Agent application settings.
Loaded once via lru_cache; override any value with environment variables or .env file.
"""
from functools import lru_cache
from pathlib import Path
from typing import List, Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(_ROOT_ENV), str(_BACKEND_ENV), ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://procureiq:procureiq_dev@localhost:5432/procureiq"
    sync_database_url: str = "postgresql://procureiq:procureiq_dev@localhost:5432/procureiq"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ── Embedding Provider ────────────────────────────────────────────────────
    # Choices: "qwen" (Qwen3-Embedding-4B, 2560d) | "local" (BGE-768) | "gemini" | "openai" | "hash"
    # "qwen" is the default — same model used in RAG-Entreprise on this machine.
    embedding_provider: Literal["qwen", "local", "gemini", "openai", "hash"] = "qwen"
    # Qwen / DB target vector settings (matches halfvec(2560) schema)
    embedding_model: str = "Qwen/Qwen3-Embedding-4B"
    embedding_dimension: int = 2560
    qwen_base_url: str = "http://localhost:11434"   # Ollama / vLLM / llama-server endpoint (optional)
    qwen_use_http_first: bool = False               # Prefer shared HTTP Qwen server before local GPU weights
    # Local BGE fallback (used when embedding_provider="local")
    local_embedding_model: str = "BAAI/bge-base-en-v1.5"
    local_embedding_dimension: int = 768
    openai_api_key: str = ""
    allow_model_downloads: bool = True
    enable_local_models: bool = True

    # ── LLM (Gemini) ─────────────────────────────────────────────────────────
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_verify_ssl: bool = True

    # ── LangGraph / Agent ─────────────────────────────────────────────────────
    # Number of tools to retrieve per query (keep ≤ 7 for LLM focus)
    tool_retrieval_top_k: int = 5
    # Max conversation turns stored in memory
    max_session_turns: int = 20
    # PostgreSQL checkpointer table prefix
    checkpointer_table_prefix: str = "agent_"

    # ── LangSmith Observability ───────────────────────────────────────────────
    langchain_tracing_v2: bool = False          # set True to enable LangSmith
    langchain_endpoint: str = "https://api.smith.langchain.com"
    langchain_api_key: str = ""
    langchain_project: str = "procureiq-agent"

    # ── Application ───────────────────────────────────────────────────────────
    app_name: str = "ProcureIQ — Enterprise Procurement Intelligence Agent"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Security, Auth, RBAC & Multi-Tenancy ─────────────────────────────────
    auth_enabled: bool = False  # Enforced automatically when environment="production"
    auth_secret_key: str = "procureiq-dev-secret-change-in-production"
    auth_token_expire_minutes: int = 480
    api_keys_csv: str = ""      # Optional "key:tenant_id:role:user_id,..." mapping
    rate_limit_rpm: int = 120   # Sliding-window requests per minute per IP (0 disables)
    default_tenant_id: str = "default"
    po_vp_approval_threshold: float = 25000.0
    use_durable_checkpointer: bool = True

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ]

    @property
    def effective_auth_enabled(self) -> bool:
        """Require cryptographic Bearer JWT or valid X-API-Key."""
        return bool(self.auth_enabled or self.environment.lower() == "production")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
