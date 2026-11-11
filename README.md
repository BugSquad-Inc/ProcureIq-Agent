# ProcureIQ — Scalable Dynamic Tool RAG & Procurement Intelligence Agent

**ProcureIQ** is a scalable agentic system built with **LangGraph**, **FastAPI**, **PostgreSQL + pgvector (`HALFVEC(2560)`)**, and **React**, designed to orchestrate **50–500+ tools** without degrading LLM tool-selection accuracy.

---

## Core Architecture: Dynamic Tool RAG

> *Tools are to an Agentic System what Documents are to RAG.*  
> Instead of stuffing 100+ tool schemas into the LLM prompt, ProcureIQ indexes tool descriptions in PostgreSQL (`pgvector` HNSW + GIN full-text search) and retrieves only the **top-5** most relevant tools per turn via **Dense Cosine + OR-BM25 + Reciprocal Rank Fusion (RRF) + Reranking**.

### LangGraph Execution Flow

```text
START
  └─► intent_classifier   (multi-turn routing & domain classification)
        └─► tool_retriever (Tool RAG: pgvector + OR-BM25 + RRF + Reranker)
              └─► tool_selector (select best tool, extract params, check HITL)
                    ├─► hitl_gate (interrupt() for mutating write actions)
                    │      ├─► approved  ─► executor
                    │      └─► cancelled ─► synthesizer
                    └─► executor (circuit breaker + retries + audit_log)
                          └─► synthesizer (response + AIMessage)
                                └─► END
```

---

## Verified Scaling Benchmark (`50 → 500` Tools)

Measured via [`scripts/benchmark_scale.py`](scripts/benchmark_scale.py) against PostgreSQL + pgvector (`top_k=5`):

| Active Tools | Bound to LLM | Recall@5 | MRR@5 | Avg Latency | P95 Latency |
|-------------:|-------------:|---------:|------:|------------:|------------:|
| 50           | top-5        | 100.0%   | 1.000 | 9.24 ms     | 10.30 ms    |
| 100          | top-5        | 100.0%   | 1.000 | 10.80 ms    | 11.53 ms    |
| 250          | top-5        | 100.0%   | 1.000 | 18.23 ms    | 19.71 ms    |
| 500          | top-5        | 100.0%   | 1.000 | 29.36 ms    | 34.19 ms    |

---

## Key Features

- **50 Seeded PayPal & Procurement Tools** across `payments`, `invoicing`, `procurement`, `disputes`, and `analytics` (`scripts/seed_tools.py`).
- **Two Built-In Meta Tools**:
  - `rag_query`: Hybrid RAG Q&A over uploaded PDF/DOCX/TXT knowledge base documents (`kb_chunks`) with source citations.
  - `system_search`: Searches available tool capabilities and session `audit_log` history.
- **Human-in-the-Loop (HITL) Gate**: Mutating write actions (`send_payment`, `create_purchase_order`, `send_invoice`, etc.) pause via LangGraph `interrupt()` and resume via `Command(resume=...)`.
- **Production Resilience & Observability**: Per-service circuit breakers with exponential backoff (`app/core/resilience.py`), LangSmith `@traceable` hooks, and `/api/sessions/{id}/trace` + `/api/system/observability`.
- **Interactive React UI** (`frontend/`): Home KPI dashboard, Agent Chat with HITL approval cards, interactive 52-tool Catalog Cards with click-to-inspect details, Tool RAG Explorer, KB upload & RAG tester, Trace/Scale dashboard, and Settings.

---

## Quickstart

```bash
# 1. Configure environment
cp .env.example .env
# Add GEMINI_API_KEY (and optional LANGCHAIN_API_KEY)

# 2. Start PostgreSQL + pgvector
docker-compose up db -d

# 3. Install backend deps, migrate & seed 50 tools
cd backend
pip install -r requirements.txt
python -m alembic upgrade head
python ../scripts/seed_tools.py

# 4. Run tests (17/17 passing)
python -m pytest tests/ -v

# 5. Start backend (port 8000) & frontend (port 5175)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
cd ../frontend && npm install && npm run dev -- --port 5175
```

- **Web UI**: `http://localhost:5175`
- **API Docs**: `http://localhost:8000/docs`
- **Demo Guide**: [`docs/DEMO_SCRIPT.txt`](docs/DEMO_SCRIPT.txt)
