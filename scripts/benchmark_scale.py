"""
benchmark_scale.py — Automated 50 -> 100 -> 250 -> 500 Tool Scaling Benchmark.

Proves the core Datazoic architectural thesis:
  Dynamic Tool RAG keeps top-5 retrieval recall high and latency flat
  as the tool registry scales from 50 tools to 500+ multi-service APIs,
  while LLM context remains strictly bounded at k=5 schemas per turn.

Usage:
  python scripts/benchmark_scale.py
  python scripts/benchmark_scale.py --keep   # retain 500 tools in DB for live UI demo
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import uuid
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

BENCHMARK_QUERIES = [
    {"query": "Send an invoice for $50 to client@example.com", "expected": {"send_invoice", "create_invoice"}},
    {"query": "What was my total sales volume last month?", "expected": {"get_sales_report", "get_revenue_breakdown"}},
    {"query": "Is there a dispute open from user_123?", "expected": {"get_dispute", "list_disputes"}},
    {"query": "Create a purchase order for server hardware from Acme Corp", "expected": {"create_purchase_order"}},
    {"query": "Issue a full or partial refund for a customer payment", "expected": {"refund_payment"}},
    {"query": "Check current available PayPal account balance", "expected": {"get_balance"}},
    {"query": "Send batch payouts to multiple vendors and contractors", "expected": {"create_payout_batch"}},
    {"query": "Flag price mismatch between vendor invoice and purchase order", "expected": {"flag_invoice_discrepancy"}},
    {"query": "List all registered suppliers and vendors", "expected": {"list_vendors"}},
    {"query": "Track department budget utilization for this quarter", "expected": {"get_budget_utilization"}},
]

SYNTHETIC_DOMAINS = [
    ("crm", "Salesforce / HubSpot", ["contact", "deal", "lead", "account", "opportunity", "pipeline"]),
    ("devops", "AWS / Kubernetes", ["cluster", "deployment", "bucket", "lambda", "container", "log_group"]),
    ("hr", "Workday / BambooHR", ["employee", "payroll", "leave_balance", "onboarding", "timesheet", "review"]),
    ("support", "Zendesk / Jira", ["ticket", "sprint", "issue_board", "sla_queue", "escalation", "macro"]),
    ("logistics", "FedEx / SAP SCM", ["waybill", "warehouse_bin", "freight_quote", "customs_entry", "dock_slot", "carrier"]),
]
SYNTHETIC_VERBS = ["sync", "archive", "tag", "assign", "export", "preview", "audit", "clone", "subscribe", "notify", "merge", "validate", "schedule", "close", "reopen"]


def generate_distractor_tools(count: int, prefix: str) -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    for i in range(count):
        domain, platform, nouns = SYNTHETIC_DOMAINS[i % len(SYNTHETIC_DOMAINS)]
        noun = nouns[(i // len(SYNTHETIC_DOMAINS)) % len(nouns)]
        verb = SYNTHETIC_VERBS[(i // (len(SYNTHETIC_DOMAINS) * len(nouns))) % len(SYNTHETIC_VERBS)]
        tools.append(
            {
                "name": f"{prefix}{domain}_{verb}_{noun}_{i:03d}",
                "domain": domain,
                "description": (
                    f"{verb.title()} {noun.replace('_', ' ')} records in {platform} "
                    f"(enterprise connector op #{i:03d}) for workflow automation."
                ),
                "schema": {"record_id": "string", "workspace": "string"},
                "endpoint": f"/v1/{domain}/{noun}/{verb}",
            }
        )
    return tools


async def run_benchmark(keep_synthetic: bool = False) -> Dict[str, Any]:
    from sqlalchemy import delete, func, select
    from app.infrastructure.database.models import Tool
    from app.infrastructure.database.session import AsyncSessionLocal, engine
    from app.tools.registry import upsert_tools_batch
    from app.tools.retriever import ToolRetriever

    prefix = "bench500_"
    tiers = [50, 100, 250, 500]
    results: List[Dict[str, Any]] = []

    try:
        async with AsyncSessionLocal() as session:
            # Ensure clean baseline of 50 tools
            await session.execute(delete(Tool).where(Tool.name.like(f"{prefix}%")))
            await session.commit()

            base_count = int(
                (await session.execute(select(func.count(Tool.id)).where(Tool.is_active == True))).scalar() or 0
            )
            all_distractors = generate_distractor_tools(max(0, 500 - base_count), prefix=prefix)

            # Warm up embedding & reranker provider once so tier latencies reflect steady-state performance
            warmup_retriever = ToolRetriever(session=session)
            await warmup_retriever.retrieve(query_text="warmup tool retrieval query", top_k=5)

            inserted_so_far = 0
            for target_tier in tiers:
                needed = max(0, (target_tier - base_count) - inserted_so_far)
                if needed > 0:
                    batch = all_distractors[inserted_so_far : inserted_so_far + needed]
                    await upsert_tools_batch(session, batch, overwrite_existing=False)
                    inserted_so_far += needed

                retriever = ToolRetriever(session=session)
                hits = 0
                reciprocal_ranks: List[float] = []
                latencies: List[float] = []

                for case in BENCHMARK_QUERIES:
                    res = await retriever.retrieve(query_text=case["query"], top_k=5)
                    latencies.append(res.latency_ms)
                    names = [t.name for t in res.tools]
                    rank_rr = 0.0
                    for idx, name in enumerate(names, start=1):
                        if name in case["expected"]:
                            rank_rr = 1.0 / idx
                            break
                    if rank_rr > 0:
                        hits += 1
                    reciprocal_ranks.append(rank_rr)

                sorted_lat = sorted(latencies)
                p95_idx = min(len(sorted_lat) - 1, max(0, int(0.95 * len(sorted_lat)) - 1))
                tier_report = {
                    "total_tools": res.total_active_tools,
                    "top_k_bound": 5,
                    "queries_tested": len(BENCHMARK_QUERIES),
                    "recall_at_5": round(hits / len(BENCHMARK_QUERIES), 4),
                    "mrr_at_5": round(statistics.mean(reciprocal_ranks), 4),
                    "avg_latency_ms": round(statistics.mean(latencies), 2),
                    "p95_latency_ms": round(sorted_lat[p95_idx], 2),
                }
                results.append(tier_report)

            if not keep_synthetic:
                await session.execute(delete(Tool).where(Tool.name.like(f"{prefix}%")))
                await session.commit()
    finally:
        await engine.dispose()

    report = {
        "benchmark": "ProcureIQ Dynamic Tool RAG Scale Test",
        "tiers": results,
        "kept_synthetic_tools": keep_synthetic,
    }

    out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "scale_benchmark_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n=== ProcureIQ Tool RAG Scale Benchmark ===")
    print(f"{'Tools':>6} | {'Top-K':>5} | {'Recall@5':>8} | {'MRR@5':>6} | {'Avg ms':>8} | {'P95 ms':>8}")
    print("-" * 56)
    for row in results:
        print(
            f"{row['total_tools']:>6} | {row['top_k_bound']:>5} | "
            f"{row['recall_at_5']*100:>7.1f}% | {row['mrr_at_5']:>6.3f} | "
            f"{row['avg_latency_ms']:>8.2f} | {row['p95_latency_ms']:>8.2f}"
        )
    print(f"\nReport saved to: {os.path.abspath(out_path)}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Tool RAG scaling 50 -> 500 tools")
    parser.add_argument("--keep", action="store_true", help="Keep synthetic 500 tools in DB after benchmark")
    args = parser.parse_args()
    asyncio.run(run_benchmark(keep_synthetic=args.keep))
