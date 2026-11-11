"""
generate_solution_pdf.py — Generate the ProcureIQ Solution Architecture &
Engineering Dossier PDF. Renders as a formal professional IT solution document.
"""
from __future__ import annotations

from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_PDF = ROOT / "ProcureIQ_Solution_Architecture_Dossier.pdf"

HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>ProcureIQ — Solution Architecture Document</title>
<style>
  @page {
    size: A4;
    margin: 20mm 18mm 22mm 18mm;
    @top-left {
      content: "ProcureIQ — Solution Architecture & Engineering Document";
      font-family: Arial, sans-serif;
      font-size: 7.5pt;
      color: #555555;
    }
    @top-right {
      content: "Version 1.0 | Confidential";
      font-family: Arial, sans-serif;
      font-size: 7.5pt;
      color: #555555;
    }
    @bottom-left {
      content: "Enterprise FinTech & Procurement AI Platform";
      font-family: Arial, sans-serif;
      font-size: 7.5pt;
      color: #555555;
    }
    @bottom-right {
      content: "Page " counter(page) " of " counter(pages);
      font-family: Arial, sans-serif;
      font-size: 7.5pt;
      color: #333333;
    }
  }
  @page :first {
    @top-left  { content: none; }
    @top-right { content: none; }
    @bottom-left  { content: none; }
    @bottom-right { content: none; }
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 10pt;
    line-height: 1.55;
    color: #1a1a1a;
    background: #ffffff;
  }

  /* ── Cover Page ─────────────────────────── */
  .cover {
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: 240mm;
    padding: 0 4mm;
  }
  .cover-rule-top {
    border-top: 4px solid #1a3a5c;
    margin-bottom: 28px;
  }
  .cover-rule-bottom {
    border-top: 1px solid #1a3a5c;
    margin-top: 28px;
  }
  .cover-label {
    font-size: 9pt;
    font-weight: bold;
    color: #1a3a5c;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 10px;
  }
  .cover-title {
    font-size: 22pt;
    font-weight: bold;
    color: #1a1a1a;
    line-height: 1.2;
    margin-bottom: 14px;
  }
  .cover-subtitle {
    font-size: 13pt;
    color: #333333;
    font-weight: normal;
    margin-bottom: 20px;
  }
  .cover-meta {
    font-size: 9.5pt;
    color: #444444;
    line-height: 1.8;
  }
  .cover-meta td {
    padding: 1px 0;
    border: none;
    background: none;
  }
  .cover-meta td:first-child {
    color: #666666;
    padding-right: 20px;
    min-width: 90px;
  }

  /* ── Section headings ───────────────────── */
  h1 {
    font-size: 13pt;
    font-weight: bold;
    color: #1a3a5c;
    border-bottom: 2px solid #1a3a5c;
    padding-bottom: 4px;
    margin: 18px 0 10px 0;
    page-break-after: avoid;
  }
  h2 {
    font-size: 11pt;
    font-weight: bold;
    color: #1a1a1a;
    margin: 14px 0 6px 0;
    page-break-after: avoid;
  }
  h3 {
    font-size: 10pt;
    font-weight: bold;
    color: #1a3a5c;
    margin: 10px 0 4px 0;
    page-break-after: avoid;
  }

  p  { margin: 0 0 8px 0; }
  ul { margin: 4px 0 8px 0; padding-left: 18px; }
  ol { margin: 4px 0 8px 0; padding-left: 18px; }
  li { margin-bottom: 4px; }

  code {
    font-family: Consolas, 'Courier New', monospace;
    font-size: 8.8pt;
    background: #f4f4f4;
    border: 1px solid #dddddd;
    padding: 0 3px;
    border-radius: 2px;
    color: #1a1a1a;
  }

  /* ── Tables ─────────────────────────────── */
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 6px 0 12px 0;
    font-size: 9pt;
    page-break-inside: avoid;
  }
  th {
    background: #1a3a5c;
    color: #ffffff;
    text-align: left;
    padding: 6px 9px;
    font-weight: bold;
    font-size: 8.8pt;
  }
  td {
    padding: 5.5px 9px;
    border: 1px solid #cccccc;
    vertical-align: top;
  }
  tr:nth-child(even) td { background: #f7f9fb; }

  /* ── Info box (replaces callout) ─────────── */
  .infobox {
    border: 1px solid #c0cfe0;
    border-left: 4px solid #1a3a5c;
    background: #f4f7fb;
    padding: 8px 12px;
    margin: 8px 0 12px 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
  }

  /* ── Algo steps ─────────────────────────── */
  .algo-table {
    width: 100%;
    border-collapse: collapse;
    margin: 6px 0 10px 0;
    font-size: 9pt;
    page-break-inside: avoid;
  }
  .algo-table td {
    padding: 5px 9px;
    border: 1px solid #cccccc;
    vertical-align: top;
  }
  .algo-table .step-num {
    font-weight: bold;
    color: #1a3a5c;
    white-space: nowrap;
    width: 70px;
    background: #f4f7fb;
  }
  .algo-formula {
    font-family: Consolas, 'Courier New', monospace;
    font-size: 8.5pt;
    background: #f4f4f4;
    border: 1px solid #dddddd;
    padding: 3px 8px;
    margin-top: 4px;
    display: block;
    color: #1a1a1a;
  }

  /* ── Summary metrics strip ──────────────── */
  .metrics-table {
    width: 100%;
    border-collapse: collapse;
    margin: 6px 0 12px 0;
  }
  .metrics-table td {
    border: 1px solid #cccccc;
    padding: 7px 10px;
    text-align: center;
    width: 25%;
    background: #f7f9fb;
    vertical-align: top;
  }
  .metrics-table .m-val {
    font-size: 12pt;
    font-weight: bold;
    color: #1a3a5c;
    display: block;
  }
  .metrics-table .m-lbl {
    font-size: 8pt;
    color: #444444;
    display: block;
    margin-top: 2px;
  }

  /* ── Diagram wrapper ────────────────────── */
  .diagram-wrap {
    border: 1px solid #cccccc;
    background: #fafafa;
    padding: 8px;
    margin: 8px 0 10px 0;
    page-break-inside: avoid;
    text-align: center;
  }
  .diagram-caption {
    font-size: 8pt;
    color: #555555;
    font-style: italic;
    margin-top: 5px;
    text-align: center;
  }

  /* ── Two-column ─────────────────────────── */
  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-bottom: 10px;
  }
  .col-box {
    border: 1px solid #cccccc;
    padding: 8px 11px;
    font-size: 9.5pt;
    page-break-inside: avoid;
  }
  .col-box h3 { margin-top: 0; }

  /* ── Flow steps (numbered list style) ───── */
  .flow-steps {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 8px;
    margin: 6px 0 10px 0;
  }
  .flow-step {
    border: 1px solid #cccccc;
    border-top: 3px solid #1a3a5c;
    padding: 7px 9px;
    font-size: 9pt;
    page-break-inside: avoid;
  }
  .flow-step .step-title {
    font-weight: bold;
    color: #1a3a5c;
    display: block;
    margin-bottom: 3px;
    font-size: 9pt;
  }

  .page-break { page-break-before: always; }
  .section-num { color: #1a3a5c; }
</style>
</head>
<body>

<!-- ==================== COVER PAGE ==================== -->
<div class="cover">
  <div class="cover-rule-top"></div>
  <div class="cover-label">Solution Architecture &amp; Engineering Document</div>
  <div class="cover-title">ProcureIQ<br>Enterprise Agentic FinTech &amp;<br>Procurement Intelligence Platform</div>
  <div class="cover-subtitle">System Design, AI Architecture &amp; Production Engineering Reference</div>
  <table class="cover-meta">
    <tr><td>Document Type</td><td>Solution Architecture Document (SAD)</td></tr>
    <tr><td>Version</td><td>1.0</td></tr>
    <tr><td>Classification</td><td>Confidential — Internal / Interview Use</td></tr>
    <tr><td>Platform</td><td>Multi-Tenant Agentic RAG System with HITL Governance</td></tr>
    <tr><td>Tech Stack</td><td>FastAPI · LangGraph · PostgreSQL/pgvector · Qwen3-4B · Gemini</td></tr>
    <tr><td>Test Coverage</td><td>31/31 Automated Tests Passing (Phases 1–5)</td></tr>
  </table>
  <div class="cover-rule-bottom"></div>
</div>

<!-- ==================== PAGE 2: EXECUTIVE SUMMARY + ARCHITECTURE ==================== -->
<div class="page-break"></div>

<h1><span class="section-num">1.</span> Executive Summary</h1>
<p>
  ProcureIQ is a production-grade, multi-tenant agentic AI platform designed to automate enterprise FinTech and procurement workflows. The platform combines a stateful LangGraph orchestration engine, hybrid vector + full-text retrieval, role-based access control (RBAC), and human-in-the-loop (HITL) approval governance into a single cohesive architecture.
</p>
<p>
  The core design challenge addressed by this system is <strong>scalable tool-calling</strong>: rather than injecting all API tool definitions into every LLM prompt (which grows linearly with registry size), ProcureIQ retrieves only the most relevant tools per query using the same retrieval algorithms applied to documents in a traditional RAG pipeline. This keeps LLM context size constant regardless of how many tools are registered.
</p>

<table class="metrics-table">
  <tr>
    <td><span class="m-val">O(k) constant</span><span class="m-lbl">Tool binding complexity — 50 to 500+ tools, always top-k=5 retrieved</span></td>
    <td><span class="m-val">&ge; 87.5% Recall@5</span><span class="m-lbl">Verified at &lt; 200ms latency on 500-tool benchmark</span></td>
    <td><span class="m-val">2560d HALFVEC</span><span class="m-lbl">Qwen3-4B FP16 embeddings in PostgreSQL pgvector</span></td>
    <td><span class="m-val">31 / 31</span><span class="m-lbl">Automated integration tests passing across all phases</span></td>
  </tr>
</table>

<h1><span class="section-num">2.</span> System Architecture</h1>
<p>
  The system is structured as a layered architecture with clearly separated concerns across transport security, cognitive orchestration, hybrid retrieval, policy enforcement, and durable persistence. Figure 1 illustrates the high-level component topology.
</p>

<div class="diagram-wrap">
  <svg viewBox="0 0 920 350" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" style="font-family: Arial, sans-serif;">
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#555555"/>
      </marker>
      <marker id="arrowBlue" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#1a3a5c"/>
      </marker>
    </defs>

    <!-- Client -->
    <rect x="12" y="14" width="155" height="92" rx="4" fill="#f4f7fb" stroke="#1a3a5c" stroke-width="1.4"/>
    <text x="89" y="34" text-anchor="middle" font-size="10" font-weight="bold" fill="#1a3a5c">Client &amp; Reverse Proxy</text>
    <text x="89" y="51" text-anchor="middle" font-size="8.5" fill="#333333">React 18 + Vite SPA</text>
    <text x="89" y="65" text-anchor="middle" font-size="8.5" fill="#333333">Nginx TLS / Security Headers</text>
    <text x="89" y="79" text-anchor="middle" font-size="8.2" fill="#555555">X-Tenant-ID · Role · JWT</text>
    <text x="89" y="93" text-anchor="middle" font-size="8" fill="#555555">Live Execution Trace UI</text>

    <!-- Gateway -->
    <rect x="195" y="14" width="185" height="92" rx="4" fill="#f4f7fb" stroke="#1a3a5c" stroke-width="1.4"/>
    <text x="287" y="34" text-anchor="middle" font-size="10" font-weight="bold" fill="#1a3a5c">FastAPI Security Gateway</text>
    <text x="287" y="51" text-anchor="middle" font-size="8.5" fill="#333333">RateLimitMiddleware (429/min)</text>
    <text x="287" y="65" text-anchor="middle" font-size="8.5" fill="#333333">HS256 JWT + API Key Auth (401)</text>
    <text x="287" y="79" text-anchor="middle" font-size="8.5" fill="#333333">RBAC Engine (VP &gt; $25k → 403)</text>
    <text x="287" y="93" text-anchor="middle" font-size="8.2" fill="#555555">Pydantic v2 + RequestValidation (422)</text>

    <!-- AI Models -->
    <rect x="408" y="14" width="269" height="92" rx="4" fill="#f4f7fb" stroke="#1a3a5c" stroke-width="1.4"/>
    <text x="542" y="34" text-anchor="middle" font-size="10" font-weight="bold" fill="#1a3a5c">AI Models &amp; Resilience Adapters</text>
    <text x="542" y="51" text-anchor="middle" font-size="8.5" fill="#333333">Qwen3-Embedding-4B (CUDA FP16 2560d / HTTP)</text>
    <text x="542" y="65" text-anchor="middle" font-size="8.5" fill="#333333">Gemini Flash-Lite Cascade (TLS + Function Calls)</text>
    <text x="542" y="79" text-anchor="middle" font-size="8.5" fill="#333333">CrossEncoder ms-marco-MiniLM-L-6-v2</text>
    <text x="542" y="93" text-anchor="middle" font-size="8.2" fill="#555555">CircuitBreaker (3 fails → 30s) + Backoff Retries</text>

    <!-- LangGraph Box -->
    <rect x="12" y="128" width="665" height="122" rx="4" fill="#ffffff" stroke="#333333" stroke-width="1.4"/>
    <text x="24" y="146" font-size="10" font-weight="bold" fill="#1a3a5c">LangGraph Cyclic StateGraph — Thread-Scoped with Durable PostgreSQL Checkpointing</text>

    <rect x="24" y="158" width="96" height="52" rx="3" fill="#f4f7fb" stroke="#1a3a5c" stroke-width="1.2"/>
    <text x="72" y="177" text-anchor="middle" font-size="8.8" font-weight="bold" fill="#1a3a5c">1. Intent Router</text>
    <text x="72" y="191" text-anchor="middle" font-size="7.8" fill="#333333">Gemini Supervisor</text>
    <text x="72" y="203" text-anchor="middle" font-size="7.8" fill="#333333">+ Scope/Greeting Guard</text>

    <rect x="136" y="158" width="108" height="52" rx="3" fill="#f4f7fb" stroke="#1a3a5c" stroke-width="1.2"/>
    <text x="190" y="177" text-anchor="middle" font-size="8.8" font-weight="bold" fill="#1a3a5c">2. Tool Retriever</text>
    <text x="190" y="191" text-anchor="middle" font-size="7.8" fill="#333333">Dense + BM25 + RRF</text>
    <text x="190" y="203" text-anchor="middle" font-size="7.8" fill="#333333">+ Cross-Encoder (Top 5)</text>

    <rect x="260" y="158" width="112" height="52" rx="3" fill="#f4f7fb" stroke="#1a3a5c" stroke-width="1.2"/>
    <text x="316" y="177" text-anchor="middle" font-size="8.8" font-weight="bold" fill="#1a3a5c">3. Tool Selector</text>
    <text x="316" y="191" text-anchor="middle" font-size="7.8" fill="#333333">KB Entity Enrichment</text>
    <text x="316" y="203" text-anchor="middle" font-size="7.8" fill="#333333">+ Gemini Function Call</text>

    <rect x="388" y="154" width="94" height="36" rx="3" fill="#fff9e6" stroke="#888800" stroke-width="1.2"/>
    <text x="435" y="170" text-anchor="middle" font-size="8.5" font-weight="bold" fill="#555500">4a. HITL Gate</text>
    <text x="435" y="182" text-anchor="middle" font-size="7.5" fill="#555500">interrupt() Writes</text>

    <rect x="388" y="200" width="94" height="36" rx="3" fill="#f0faf0" stroke="#226622" stroke-width="1.2"/>
    <text x="435" y="216" text-anchor="middle" font-size="8.5" font-weight="bold" fill="#226622">4b. Executor</text>
    <text x="435" y="228" text-anchor="middle" font-size="7.5" fill="#226622">RBAC + CircuitBreaker</text>

    <rect x="502" y="158" width="160" height="52" rx="3" fill="#f4f7fb" stroke="#1a3a5c" stroke-width="1.2"/>
    <text x="582" y="177" text-anchor="middle" font-size="8.8" font-weight="bold" fill="#1a3a5c">5. Response Synthesizer</text>
    <text x="582" y="191" text-anchor="middle" font-size="7.8" fill="#333333">Grounded Citations, IDs,</text>
    <text x="582" y="203" text-anchor="middle" font-size="7.8" fill="#333333">Error Recovery &amp; Out-of-Scope</text>

    <line x1="120" y1="184" x2="134" y2="184" stroke="#1a3a5c" stroke-width="1.4" marker-end="url(#arrowBlue)"/>
    <line x1="244" y1="184" x2="258" y2="184" stroke="#1a3a5c" stroke-width="1.4" marker-end="url(#arrowBlue)"/>
    <line x1="372" y1="174" x2="386" y2="172" stroke="#555555" stroke-width="1.2" marker-end="url(#arrow)"/>
    <line x1="372" y1="194" x2="386" y2="216" stroke="#555555" stroke-width="1.2" marker-end="url(#arrow)"/>
    <line x1="435" y1="190" x2="435" y2="198" stroke="#555555" stroke-width="1.2" marker-end="url(#arrow)"/>
    <line x1="482" y1="218" x2="500" y2="194" stroke="#555555" stroke-width="1.2" marker-end="url(#arrow)"/>
    <line x1="482" y1="170" x2="500" y2="174" stroke="#555555" stroke-width="1.2" stroke-dasharray="4,2" marker-end="url(#arrow)"/>

    <!-- PostgreSQL -->
    <rect x="698" y="14" width="210" height="236" rx="4" fill="#1a3a5c" stroke="#0d1f35" stroke-width="1.4"/>
    <text x="803" y="36" text-anchor="middle" font-size="10" font-weight="bold" fill="#ffffff">PostgreSQL 16 + pgvector</text>
    <rect x="711" y="48" width="184" height="44" rx="3" fill="#243f60" stroke="#3a5c80"/>
    <text x="803" y="64" text-anchor="middle" font-size="8.5" font-weight="bold" fill="#ffffff">tools — API Registry (50+)</text>
    <text x="803" y="78" text-anchor="middle" font-size="7.8" fill="#c8d8e8">HALFVEC(2560) HNSW + GIN FTS</text>

    <rect x="711" y="99" width="184" height="44" rx="3" fill="#243f60" stroke="#3a5c80"/>
    <text x="803" y="115" text-anchor="middle" font-size="8.5" font-weight="bold" fill="#ffffff">kb_chunks — Doc Store (54+)</text>
    <text x="803" y="129" text-anchor="middle" font-size="7.8" fill="#c8d8e8">Tenant-Scoped HNSW + OR-BM25</text>

    <rect x="711" y="150" width="184" height="44" rx="3" fill="#243f60" stroke="#3a5c80"/>
    <text x="803" y="166" text-anchor="middle" font-size="8.5" font-weight="bold" fill="#ffffff">agent_checkpoints / blobs</text>
    <text x="803" y="180" text-anchor="middle" font-size="7.8" fill="#c8d8e8">Durable Restart-Safe LangGraph State</text>

    <rect x="711" y="201" width="184" height="38" rx="3" fill="#243f60" stroke="#3a5c80"/>
    <text x="803" y="217" text-anchor="middle" font-size="8.5" font-weight="bold" fill="#ffffff">sessions + audit_log</text>
    <text x="803" y="230" text-anchor="middle" font-size="7.8" fill="#c8d8e8">Immutable Tenant Trace + RBAC Denials</text>

    <!-- Observability bar -->
    <rect x="12" y="272" width="896" height="64" rx="4" fill="#f4f7fb" stroke="#aaaaaa" stroke-width="1.1"/>
    <text x="26" y="290" font-size="9.5" font-weight="bold" fill="#1a3a5c">Observability, Explainability &amp; Adapter Layer</text>
    <text x="26" y="308" font-size="8.2" fill="#333333">•  Execution Step Telemetry (_merge_execution_steps)   •  /api/sessions/{id}/trace — exposes Cosine, BM25, RRF, Rerank scores and Circuit Breaker state</text>
    <text x="26" y="323" font-size="8.2" fill="#333333">•  LangSmith @traceable Spans   •  Structlog Structured Events   •  PayPal/FinTech Adapter: 50 operations across 9 business domains</text>

    <!-- Connector lines -->
    <line x1="167" y1="60" x2="193" y2="60" stroke="#555555" stroke-width="1.5" marker-end="url(#arrow)"/>
    <line x1="287" y1="106" x2="287" y2="126" stroke="#1a3a5c" stroke-width="1.5" marker-end="url(#arrowBlue)"/>
    <line x1="380" y1="60" x2="406" y2="60" stroke="#555555" stroke-width="1.5" marker-end="url(#arrow)"/>
    <line x1="542" y1="106" x2="542" y2="126" stroke="#555555" stroke-width="1.4" marker-end="url(#arrow)"/>
    <line x1="677" y1="184" x2="696" y2="184" stroke="#1a3a5c" stroke-width="1.6" marker-end="url(#arrowBlue)"/>
    <line x1="677" y1="70" x2="696" y2="70" stroke="#555555" stroke-width="1.4" marker-end="url(#arrow)"/>
    <line x1="450" y1="250" x2="450" y2="270" stroke="#555555" stroke-width="1.3" marker-end="url(#arrow)"/>
  </svg>
  <div class="diagram-caption">Figure 1: ProcureIQ System Architecture — Security Gateway, LangGraph Orchestration DAG, Hybrid Retrieval Engine, and Persistence Tier</div>
</div>

<!-- ==================== PAGE 3: ARCHITECTURAL DECISIONS + LIFECYCLE ==================== -->
<div class="page-break"></div>

<h1><span class="section-num">3.</span> Architectural Design Decisions</h1>
<p>The following table documents the principal architectural choices made during the design of ProcureIQ, the rationale behind each, and the alternative approaches that were evaluated and rejected.</p>

<table>
  <thead>
    <tr>
      <th style="width: 23%;">Design Decision</th>
      <th style="width: 40%;">Rationale</th>
      <th style="width: 37%;">Rejected Alternatives &amp; Risk Avoided</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>LangGraph Cyclic StateGraph with interrupt()</strong></td>
      <td>Enables clean separation of intent routing, retrieval, enrichment, safety gating, execution, and synthesis into independently testable, deterministic graph nodes. Supports stateful pause/resume across HTTP turns for financial write operations requiring human approval.</td>
      <td>Stateless ReAct loops cannot pause mid-execution for human confirmation. Single-shot chains cannot maintain multi-user RBAC handoff state across separate HTTP requests.</td>
    </tr>
    <tr>
      <td><strong>Custom asyncpg PostgresCheckpointSaver</strong></td>
      <td>Stores full graph snapshots, channel blobs, and pending writes in PostgreSQL via SQLAlchemy ON CONFLICT upserts. Shares the application's existing connection pool, eliminating a separate persistence service.</td>
      <td>InMemorySaver loses all pending HITL approvals on server restart or multi-worker load balancing. The official psycopg3 async saver triggers Windows ProactorEventLoop conflicts and splits SQLAlchemy's connection pool.</td>
    </tr>
    <tr>
      <td><strong>Dynamic Tool RAG — Top-k Binding</strong></td>
      <td>Decouples tool registry growth from LLM context size. Only the top-5 most relevant tool schemas are injected per query, maintaining constant O(k) prompt token count regardless of whether 50 or 500 tools are registered.</td>
      <td>Injecting all tool schemas into every system prompt causes O(N) token growth, exhausts context windows, and significantly reduces tool selection accuracy due to attention dilution on near-duplicate operations.</td>
    </tr>
    <tr>
      <td><strong>PostgreSQL as Unified Data Store</strong></td>
      <td>A single PostgreSQL 16 instance handles HNSW vector search, BM25 full-text retrieval, transactional sessions, durable checkpoints, and an immutable audit log — all within one ACID-compliant database with full tenant isolation via indexed tenant_id predicates.</td>
      <td>Separate vector databases (Pinecone, Qdrant) + Redis + PostgreSQL increases operational complexity, introduces eventual-consistency issues on record deletes, and complicates tenant isolation boundary enforcement.</td>
    </tr>
    <tr>
      <td><strong>Pre-Selection Knowledge Base Enrichment</strong></td>
      <td>Entity identifiers (invoice IDs, PO numbers, emails, amounts) are resolved from the tenant's knowledge base and prior audit logs before the LLM selects and parameterises a tool. This ensures that all required parameters are available at function-call time.</td>
      <td>Requiring the LLM to call a lookup tool first to retrieve missing parameters creates multi-turn ambiguity, risks incorrect parameter binding, and fails HITL pre-validation for financial operations.</td>
    </tr>
  </tbody>
</table>

<h2>3.1 End-to-End Request Lifecycle</h2>
<p>The following walkthrough traces a representative high-risk request ("Approve purchase order PO-2026-0301 for $32,000") through each system component to illustrate how security, retrieval, durable state, and RBAC enforcement interact:</p>

<div class="flow-steps">
  <div class="flow-step">
    <span class="step-title">Step 1 — Gateway &amp; Authentication</span>
    The rate limiter validates the sliding-window IP quota. <code>get_auth_context</code> resolves tenant_id and RBAC role (operator) from the HS256 JWT token and enforces session ownership.
  </div>
  <div class="flow-step">
    <span class="step-title">Step 2 — Intent Classification &amp; Tool Retrieval</span>
    The intent classifier routes to the <em>procurement</em> domain. The tool retriever embeds the query via Qwen3-4B GPU, executes HNSW + GIN OR-BM25 + RRF + Cross-Encoder reranking across 50 registered tools, and binds the top-5 candidates.
  </div>
  <div class="flow-step">
    <span class="step-title">Step 3 — KB Enrichment &amp; Tool Selection</span>
    <code>_enrich_params_from_kb</code> resolves the PO document (vendor: Aegis Cyber, amount: $32,000). Gemini's native functionCall mechanism selects <code>approve_purchase_order</code>.
  </div>
  <div class="flow-step">
    <span class="step-title">Step 4 — Durable HITL Pause</span>
    As a registered write-class operation, <code>hitl_gate</code> calls <code>interrupt()</code>, persisting the full graph state (channel blobs + pending writes) to PostgreSQL. The state survives server restarts.
  </div>
  <div class="flow-step">
    <span class="step-title">Step 5 — RBAC Policy Enforcement</span>
    If an operator attempts to confirm, <code>enforce_tool_rbac</code> returns HTTP 403, citing the $25,000 Finance VP approval threshold, while leaving the checkpoint intact for a qualified approver.
  </div>
  <div class="flow-step">
    <span class="step-title">Step 6 — VP Approval &amp; Audit</span>
    A finance_vp resumes the session via <code>/api/chat/confirm</code>. The approver_role is injected into the resumed state; the executor runs behind a CircuitBreaker and writes a full audit trace to audit_log.
  </div>
</div>

<h2>3.2 Enterprise Domain Coverage</h2>
<p>The tool registry covers <strong>9 capability domains</strong> across 50 registered API operations: Payments &amp; Treasury (captures, payouts, refunds, subscriptions), Invoicing &amp; 3-Way Match Discrepancy Resolution, Procurement (purchase orders, goods receipts, RFQs, vendor onboarding), Disputes &amp; Risk/KYC, Financial Analytics, Webhook Management, Knowledge Base RAG (54 indexed documents in TXT, MD, PDF, and DOCX formats including contracts, SLAs, budget reports, SOC2 and FINRA governance SOPs), and System Introspection.</p>

<!-- ==================== PAGE 4: AI + ALGORITHMS ==================== -->
<div class="page-break"></div>

<h1><span class="section-num">4.</span> AI Models &amp; Retrieval Algorithms</h1>

<h2>4.1 Model Stack</h2>
<div class="two-col">
  <div class="col-box">
    <h3>Embedding Model — Qwen3-Embedding-4B</h3>
    <p>Executed natively on CUDA GPU in FP16 half-precision via HuggingFace Transformers (device_map auto, 6,800 MiB VRAM budget). Uses causal <strong>last-token pooling</strong> followed by L2 unit normalisation to produce 2,560-dimensional sentence embeddings. Supports an HTTP-first mode that redirects embedding requests to a shared vLLM/Ollama/TEI endpoint, enabling multi-worker deployments without duplicating GPU VRAM per worker process.</p>
  </div>
  <div class="col-box">
    <h3>Reasoning &amp; Tool Calling — Google Gemini</h3>
    <p>An ordered resilience cascade targets gemini-2.5-flash-lite → flash-lite-latest → flash-latest with TLS verification enforced. Native OpenAPI <code>functionDeclarations</code> (mode: ANY) are issued against the top-5 bound tools plus KB context window. A deterministic regex/heuristic fallback activates on 429 quota throttle responses, ensuring the system degrades gracefully without returning errors to end users.</p>
  </div>
</div>
<div class="col-box" style="margin-bottom: 10px;">
  <h3>Reranker — Cross-Encoder (ms-marco-MiniLM-L-6-v2)</h3>
  <p>After the initial hybrid retrieval pass, the top-15 candidates are re-scored using a cross-encoder cross-attention model. Scores are normalised via sigmoid to produce a [0,1] relevance probability that feeds into the composite final scoring formula. A zero-download lexical concept alignment fallback is used if the model is unavailable.</p>
</div>

<h2>4.2 HALFVEC(2560) — Design Rationale</h2>
<p>Standard open-source pgvector limits HNSW index construction on single-precision <code>vector</code> columns to a maximum of 2,000 dimensions. Qwen3-Embedding-4B outputs 2,560-dimensional vectors, exceeding this constraint. The solution uses PostgreSQL's <code>halfvec</code> type (FP16 storage), which supports HNSW indexing up to 4,000 dimensions using <code>halfvec_cosine_ops</code>. This yields full 2,560d semantic fidelity while reducing HNSW index memory consumption by approximately 50%.</p>
<p>A dimension alignment utility (<code>align_embedding_dimension</code>) applies orthogonal projection and L2 re-normalisation for any fallback embedding provider (768d BGE, 384d hash, 1536d OpenAI, 3072d Gemini), ensuring vector tables remain schema-stable across provider changes without DDL migrations.</p>

<h2>4.3 Hybrid Retrieval Pipeline — Four-Stage Algorithm</h2>
<p>The same four-stage pipeline is used for both the Knowledge Base (HybridSearchService, 54+ documents) and Dynamic Tool RAG (ToolRetriever, 50–500+ tools):</p>

<table class="algo-table">
  <tr>
    <td class="step-num">Stage 1<br>Sparse Search</td>
    <td>
      <strong>Query normalisation + OR-BM25 full-text search.</strong> Typos are corrected and stopwords are stripped. Query tokens are joined with OR operators so conversational filler words do not cause zero-result BM25 matches. Executed via PostgreSQL GIN-indexed <code>to_tsvector</code> with <code>ts_rank_cd</code> scoring.
      <span class="algo-formula">ts_q = " | ".join(tokens(normalize_query(q)))   →   ts_rank_cd(to_tsvector(doc), to_tsquery(ts_q))</span>
    </td>
  </tr>
  <tr>
    <td class="step-num">Stage 2<br>Dense Search</td>
    <td>
      <strong>pgvector HNSW approximate nearest-neighbour search</strong> over HALFVEC(2560) embeddings. Sub-linear query complexity; cosine similarity is normalised to [0.0, 1.0].
      <span class="algo-formula">cos(q, d) = max(0.0, 1.0 − (emb(d) &lt;=&gt; emb(q)))</span>
    </td>
  </tr>
  <tr>
    <td class="step-num">Stage 3<br>Rank Fusion</td>
    <td>
      <strong>Reciprocal Rank Fusion (RRF)</strong> merges sparse and dense result lists in a scale-invariant manner, without requiring score calibration or min-max normalisation between the two retrieval modalities.
      <span class="algo-formula">RRF(d) = 1 / (60 + rank_dense(d))  +  1 / (60 + rank_bm25(d))</span>
    </td>
  </tr>
  <tr>
    <td class="step-num">Stage 4<br>Final Scoring</td>
    <td>
      <strong>Composite score with Intent Safety Multiplier.</strong> Blends RRF, Cross-Encoder relevance, and cosine similarity. Destructive tools (cancel, void, delete) are penalised on lookup-intent queries via the M_intent multiplier to prevent write-on-read hallucinations. Values: 0.55× for destructive verbs, 0.65× for mutating writes on lookup cues, 1.0× otherwise.
      <span class="algo-formula">S_final(t) = [ 0.45·(RRF/RRF_max)  +  0.35·sigmoid(CrossEncoder(q, t))  +  0.20·cos(q, t) ]  ×  M_intent(q, t)</span>
    </td>
  </tr>
</table>

<div class="infobox">
  <strong>Design note — OR-BM25 and M_intent in financial contexts:</strong> Standard dense retrieval ranks <em>cancel_invoice</em> and <em>get_invoice</em> nearly identically for a query such as "get me the Mike invoice already sent", since the semantic vectors overlap strongly on the shared token "invoice". The combination of OR-BM25 (for exact identifier matching), RRF (rank fusion), Cross-Encoder cross-attention, and the intent safety multiplier ensures that read-intent queries consistently bind read-only tools while write-intent operations route through HITL confirmation and RBAC enforcement.
</div>

<!-- ==================== PAGE 5: SCALABILITY + SECURITY ==================== -->
<div class="page-break"></div>

<h1><span class="section-num">5.</span> Scalability &amp; Fault Tolerance</h1>

<h2>5.1 Scalability Design</h2>
<div class="two-col">
  <div class="col-box">
    <h3>Horizontal Scalability</h3>
    <ul>
      <li><strong>Sub-linear index growth:</strong> PostgreSQL HNSW graphs and GIN inverted indexes maintain sub-200ms retrieval latency as the tool registry scales from 50 to 500+ entries, verified via the 500-tool benchmark test.</li>
      <li><strong>Stateless API workers:</strong> Storing all LangGraph state and HITL interrupts in PostgreSQL means any Uvicorn worker behind Nginx or an ALB can resume a paused workflow. Zero session affinity is required, enabling standard rolling deployments.</li>
      <li><strong>Shared embedding endpoint:</strong> Setting <code>QWEN_USE_HTTP_FIRST=true</code> routes all backend workers to a shared HTTP inference server (vLLM, Ollama, or TEI), eliminating the N × 6.5 GB VRAM overhead of loading the embedding model per worker process.</li>
    </ul>
  </div>
  <div class="col-box">
    <h3>Performance Benchmarks</h3>
    <table>
      <thead>
        <tr><th>Benchmark</th><th>Measured Result</th></tr>
      </thead>
      <tbody>
        <tr><td>500-Tool Scale Test (Recall@5)</td><td><strong>&ge; 87.5%</strong> at &lt; 200 ms</td></tr>
        <tr><td>Live Top-1 Accuracy (6 domain probes, 50 tools)</td><td><strong>6/6 (100%)</strong>, mean 421 ms warm</td></tr>
        <tr><td>54-Document KB Ingestion (TXT/MD/PDF/DOCX)</td><td><strong>54/54</strong> docs, 124.57s (~2.3s/doc GPU)</td></tr>
        <tr><td>Durable HITL Restart Test (PO $32k)</td><td>Survived process kill + reboot, 200 OK</td></tr>
      </tbody>
    </table>
    <p style="margin-top:6px;font-size:9pt;"><strong>Connection pooling:</strong> FastAPI + asyncpg + SQLAlchemy async pool (pool_size=10, max_overflow=20) prevents event-loop starvation while offloading CUDA tensor operations to executor threads.</p>
  </div>
</div>

<h2>5.2 Resilience — Circuit Breaker State Machine</h2>
<p>A per-adapter circuit breaker (implemented in resilience.py) wraps each external integration (PayPal API, RAG service, system search). It transitions through three states to prevent cascading failures:</p>

<div class="diagram-wrap">
  <svg viewBox="0 0 900 132" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" style="font-family: Arial, sans-serif;">
    <defs>
      <marker id="arr2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#555555"/>
      </marker>
    </defs>
    <rect x="8" y="8" width="435" height="116" rx="3" fill="#ffffff" stroke="#aaaaaa" stroke-width="1.2"/>
    <text x="20" y="25" font-size="9.5" font-weight="bold" fill="#1a3a5c">Per-Adapter Circuit Breaker — State Transitions</text>

    <rect x="20" y="42" width="95" height="48" rx="3" fill="#f0faf0" stroke="#226622" stroke-width="1.3"/>
    <text x="67" y="62" text-anchor="middle" font-size="9" font-weight="bold" fill="#226622">CLOSED</text>
    <text x="67" y="76" text-anchor="middle" font-size="7.5" fill="#226622">Normal operation</text>
    <text x="67" y="87" text-anchor="middle" font-size="7.5" fill="#226622">2 retries + backoff</text>

    <rect x="172" y="42" width="104" height="48" rx="3" fill="#fff0f0" stroke="#cc2222" stroke-width="1.3"/>
    <text x="224" y="62" text-anchor="middle" font-size="9" font-weight="bold" fill="#cc2222">OPEN (Fail-Fast)</text>
    <text x="224" y="76" text-anchor="middle" font-size="7.5" fill="#cc2222">Rejects immediately</text>
    <text x="224" y="87" text-anchor="middle" font-size="7.5" fill="#cc2222">CircuitOpenError (30s)</text>

    <rect x="330" y="42" width="100" height="48" rx="3" fill="#fffaf0" stroke="#886600" stroke-width="1.3"/>
    <text x="380" y="62" text-anchor="middle" font-size="9" font-weight="bold" fill="#886600">HALF-OPEN</text>
    <text x="380" y="76" text-anchor="middle" font-size="7.5" fill="#886600">Single canary probe</text>
    <text x="380" y="87" text-anchor="middle" font-size="7.5" fill="#886600">allowed through</text>

    <line x1="115" y1="60" x2="170" y2="60" stroke="#cc2222" stroke-width="1.3" marker-end="url(#arr2)"/>
    <text x="142" y="54" text-anchor="middle" font-size="7" font-weight="bold" fill="#cc2222">3 failures</text>
    <line x1="276" y1="66" x2="328" y2="66" stroke="#886600" stroke-width="1.3" marker-end="url(#arr2)"/>
    <text x="302" y="60" text-anchor="middle" font-size="7" font-weight="bold" fill="#886600">&gt;= 30s</text>
    <path d="M 380 90 Q 224 122 67 90" fill="none" stroke="#226622" stroke-width="1.2" marker-end="url(#arr2)"/>
    <text x="224" y="118" text-anchor="middle" font-size="7.2" font-weight="bold" fill="#226622">Probe succeeds → reset counter  (or admin POST /api/system/circuit-breaker/reset)</text>

    <rect x="458" y="8" width="434" height="116" rx="3" fill="#ffffff" stroke="#aaaaaa" stroke-width="1.2"/>
    <text x="470" y="25" font-size="9.5" font-weight="bold" fill="#1a3a5c">Four-Pillar Observability Architecture</text>
    <text x="470" y="45" font-size="8.5" fill="#333333"><tspan font-weight="bold">1. UI Execution Trace:</tspan>  Real-time per-node step timing and KB provenance indicators</text>
    <text x="470" y="63" font-size="8.5" fill="#333333"><tspan font-weight="bold">2. Forensic Trace API:</tspan>  /api/sessions/{id}/trace — all 5 candidates, RRF and rerank scores</text>
    <text x="470" y="81" font-size="8.5" fill="#333333"><tspan font-weight="bold">3. System Health Endpoint:</tspan>  /health and /api/system/observability — vector counts, breaker states</text>
    <text x="470" y="99" font-size="8.5" fill="#333333"><tspan font-weight="bold">4. Distributed Tracing:</tspan>  Structlog structured events + LangSmith @traceable LLM spans</text>
    <text x="470" y="117" font-size="7.8" fill="#666666">Every agent action, HITL decision, circuit breaker trip, and RBAC denial is written append-only to audit_log.</text>
  </svg>
  <div class="diagram-caption">Figure 2: Circuit Breaker State Machine and Observability Architecture</div>
</div>

<h1><span class="section-num">6.</span> Security &amp; Input Validation</h1>
<table>
  <thead>
    <tr>
      <th style="width: 20%;">Control Area</th>
      <th style="width: 46%;">Implementation</th>
      <th style="width: 34%;">Threat / Failure Mitigated</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Authentication &amp; RBAC</strong></td>
      <td>Timing-safe HMAC-SHA256 JWT (<code>create_access_token</code>, <code>decode_access_token</code>) and API key CSV support. Four-tier RBAC: viewer, operator, finance_vp, admin. The finance_vp tier is required for approve_purchase_order operations exceeding $25,000, enforced per Vendor Onboarding Policy. The approver_role is propagated into resumed checkpoint state to prevent role downgrade on HITL resumption.</td>
      <td>Unauthorised API access (401), privilege escalation, operator self-approval of capital expenditure purchase orders (403 + rbac_denied audit entry).</td>
    </tr>
    <tr>
      <td><strong>Multi-Tenant Isolation</strong></td>
      <td>An indexed <code>tenant_id</code> column is applied as a mandatory SQL predicate in all HNSW/BM25 retrieval queries, KB CRUD operations, session state access, trace retrieval, and confirmation endpoints. Cross-tenant session ownership is enforced with 403 responses.</td>
      <td>Cross-tenant data exposure in RAG prompts or unauthorised session access.</td>
    </tr>
    <tr>
      <td><strong>Input &amp; Scope Validation</strong></td>
      <td>A three-layer scope guard (intent_classifier rules + Gemini supervisor + tool_retriever semantic score floor) handles off-topic queries (weather, trivia, general conversation) with a helpful out-of-scope response (tool_used=null), never executing tools. Pydantic v2 validates message length, session_id regex, positive-only confirmation amounts, file extensions, and 25 MB upload cap with human-readable 422 error strings.</td>
      <td>Off-topic tool hallucinations, SQL truncation, binary/empty file uploads, negative payment overrides, UI serialisation errors.</td>
    </tr>
    <tr>
      <td><strong>Rate Limiting &amp; Transport</strong></td>
      <td>Per-IP 60-second sliding-window RateLimitMiddleware returns 429 with Retry-After: 60. Gemini API TLS verification is enforced by default (GEMINI_VERIFY_SSL=true). Nginx is configured with security headers: X-Content-Type-Options: nosniff, X-Frame-Options: SAMEORIGIN, Referrer-Policy: strict-origin-when-cross-origin.</td>
      <td>Brute-force API abuse, quota exhaustion via high-frequency clients, unverified upstream TLS connections.</td>
    </tr>
  </tbody>
</table>

<!-- ==================== PAGE 6: TECH STACK ==================== -->
<div class="page-break"></div>

<h1><span class="section-num">7.</span> Technology Stack &amp; Verification</h1>

<table>
  <thead>
    <tr><th style="width: 22%;">Architecture Layer</th><th>Technologies &amp; Components</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Frontend &amp; Reverse Proxy</strong></td>
      <td>React 18, Vite 6, Lucide Icons. Multi-stage Docker build produces a static bundle served by nginx:1.27-alpine with a 25 MB upload limit, 120-second proxy timeout, and workspace-scoped tenant/role/JWT controls in SettingsPanel.jsx.</td>
    </tr>
    <tr>
      <td><strong>API &amp; Security Gateway</strong></td>
      <td>FastAPI 0.115, Uvicorn (non-reload production mode via entrypoint.sh), Pydantic v2, custom HS256 JWT + API key authentication, four-tier RBAC engine, and sliding-window RateLimitMiddleware (app/core/security.py).</td>
    </tr>
    <tr>
      <td><strong>Agent Orchestration</strong></td>
      <td>LangGraph 0.2.60 with a custom PostgresCheckpointSaver (BaseCheckpointSaver), cyclic StateGraph with interrupt()-based HITL nodes, structured execution step telemetry via _merge_execution_steps reducer, and LangSmith @traceable span instrumentation.</td>
    </tr>
    <tr>
      <td><strong>AI &amp; Retrieval Models</strong></td>
      <td>Qwen/Qwen3-Embedding-4B (HuggingFace Transformers, PyTorch FP16 CUDA), Google Gemini REST API (native functionDeclarations, ordered resilience cascade), CrossEncoder ms-marco-MiniLM-L-6-v2 (sentence-transformers), PyMuPDF (PDF parsing), python-docx (DOCX parsing).</td>
    </tr>
    <tr>
      <td><strong>Data &amp; Storage</strong></td>
      <td>PostgreSQL 16 + pgvector extension: HALFVEC(2560) HNSW index (halfvec_cosine_ops) + GIN full-text index (OR-BM25). SQLAlchemy 2.0 async core + asyncpg driver. Alembic migrations (001: schema init, 002: HALFVEC/GIN upgrade). Tables: tools, kb_chunks, sessions, agent_checkpoints, agent_checkpoint_blobs, agent_checkpoint_writes, audit_log.</td>
    </tr>
    <tr>
      <td><strong>Infrastructure &amp; Packaging</strong></td>
      <td>Docker Compose full-stack orchestration (db + backend + frontend services). Backend Dockerfile with multi-stage build. Playwright Chromium for document generation. Nginx configuration with security headers and proxy settings.</td>
    </tr>
    <tr>
      <td><strong>Automated Testing</strong></td>
      <td><strong>31/31 pytest integration tests passing</strong> across five phases: Phase 1 — Tool RAG retrieval accuracy; Phase 2 — LangGraph HITL interrupt/resume; Phase 3 — Circuit Breaker state transitions + 500-tool scale benchmark; Phase 4 — Gemini function calling + KB entity disambiguation; Phase 5 — Durable checkpoint recovery, RBAC 403 enforcement, multi-tenant isolation, JWT 401, rate limit 429, out-of-scope guard, and Pydantic 422 validation. Additional: clean Vite production build and Docker Compose YAML validation.</td>
    </tr>
  </tbody>
</table>

<h1><span class="section-num">8.</span> Known Constraints &amp; Future Enhancements</h1>
<table>
  <thead>
    <tr><th style="width: 30%;">Area</th><th>Current Constraint / Planned Enhancement</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>PayPal Live API Integration</strong></td>
      <td>The PayPal adapter is implemented in full (50 operations, sandbox-verified tool schemas, HITL and RBAC enforcement). Live production credential integration is excluded from the current scope; the adapter accepts live credentials via environment variables when available.</td>
    </tr>
    <tr>
      <td><strong>Embedding Worker Isolation</strong></td>
      <td>In the current single-node configuration, Qwen3-4B loads once per worker process. For multi-worker production deployments, setting QWEN_USE_HTTP_FIRST=true is required to route all workers to a shared inference endpoint and prevent GPU VRAM exhaustion.</td>
    </tr>
    <tr>
      <td><strong>Streaming Response Support</strong></td>
      <td>The current API returns complete responses after graph execution. Server-Sent Events (SSE) streaming is architecturally compatible with LangGraph's astream_events interface and is planned for a subsequent release.</td>
    </tr>
    <tr>
      <td><strong>Fine-Tuning &amp; Domain Adaptation</strong></td>
      <td>The current system uses off-the-shelf Qwen3-Embedding-4B without domain-specific fine-tuning. LoRA adapter training on enterprise FinTech query-document pairs is planned to further improve retrieval precision for highly specialised financial terminology.</td>
    </tr>
  </tbody>
</table>

</body>
</html>
"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(HTML_CONTENT, wait_until="networkidle")
        page.pdf(
            path=str(OUT_PDF),
            format="A4",
            print_background=True,
            display_header_footer=False,
        )
        browser.close()
    print(f"Generated PDF: {OUT_PDF} ({OUT_PDF.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
