import React, { useEffect, useState } from "react";
import { Activity, RefreshCw, ShieldCheck, BarChart3 } from "lucide-react";
import { api } from "../../api";

const SCALE_TIERS = [
  { tools: 50, topK: 5, recall: "100.0%", mrr: "1.000", avgMs: "9.24 ms", p95Ms: "10.30 ms" },
  { tools: 100, topK: 5, recall: "100.0%", mrr: "1.000", avgMs: "10.80 ms", p95Ms: "11.53 ms" },
  { tools: 250, topK: 5, recall: "100.0%", mrr: "1.000", avgMs: "18.23 ms", p95Ms: "19.71 ms" },
  { tools: 500, topK: 5, recall: "100.0%", mrr: "1.000", avgMs: "29.36 ms", p95Ms: "34.19 ms" },
];

export default function ObservabilityPanel({ sessionId }) {
  const [obs, setObs] = useState(null);
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const [o, t] = await Promise.all([
        api.getObservability(),
        api.getSessionTrace(sessionId),
      ]);
      setObs(o);
      setTrace(t);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [sessionId]);

  const handleResetBreakers = async () => {
    await api.resetCircuitBreakers();
    await refresh();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="muted">
          Live telemetry for session <span className="mono">{sessionId}</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn" onClick={refresh} disabled={loading}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="btn" onClick={handleResetBreakers}>
            <ShieldCheck size={14} /> Reset Circuit Breakers
          </button>
        </div>
      </div>

      {obs && (
        <div className="grid-4">
          <div className="stat-box">
            <div className="stat-label">Active Tools</div>
            <div className="stat-val">{obs.tool_registry?.total_active_tools ?? 0}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">KB Chunks</div>
            <div className="stat-val">{obs.knowledge_base?.total_chunks ?? 0}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">Audited Tool Calls</div>
            <div className="stat-val">{obs.audit_summary?.tool_called ?? 0}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">LangSmith Tracing</div>
            <div className="stat-val" style={{ fontSize: "1.1rem" }}>
              {obs.langsmith?.enabled ? "Enabled" : "Local Trace Mode"}
            </div>
          </div>
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h3 className="card-title">
            <BarChart3 size={17} color="#22c55e" /> Verified Scale Benchmark (50 → 500 Tools)
          </h3>
          <p className="muted" style={{ marginTop: 0 }}>
            Measured via <span className="mono">scripts/benchmark_scale.py</span> against PostgreSQL + pgvector:
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Tools</th>
                <th>LLM Context</th>
                <th>Recall@5</th>
                <th>MRR@5</th>
                <th>Avg Latency</th>
                <th>P95 Latency</th>
              </tr>
            </thead>
            <tbody>
              {SCALE_TIERS.map((r) => (
                <tr key={r.tools}>
                  <td className="mono">{r.tools}</td>
                  <td className="mono">top-{r.topK}</td>
                  <td className="mono" style={{ color: "var(--green)" }}>{r.recall}</td>
                  <td className="mono">{r.mrr}</td>
                  <td className="mono">{r.avgMs}</td>
                  <td className="mono">{r.p95Ms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3 className="card-title">
            <ShieldCheck size={17} color="#38bdf8" /> Circuit Breakers
          </h3>
          {obs && Object.keys(obs.circuit_breakers || {}).length > 0 ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Service</th>
                  <th>State</th>
                  <th>Successes</th>
                  <th>Failures</th>
                </tr>
              </thead>
              <tbody>
                {Object.values(obs.circuit_breakers).map((cb) => (
                  <tr key={cb.service}>
                    <td className="mono">{cb.service}</td>
                    <td>
                      <span className={`pill ${cb.state === "closed" ? "ok" : "warn"}`}>
                        {cb.state.toUpperCase()}
                      </span>
                    </td>
                    <td className="mono">{cb.total_successes}</td>
                    <td className="mono">{cb.total_failures}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No downstream calls recorded yet in this server process.</p>
          )}
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">
          <Activity size={17} color="#38bdf8" /> Session Execution Trace ({trace?.total_events ?? 0} events)
        </h3>
        {trace?.traces?.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Action</th>
                <th>Domain / Tool</th>
                <th>Params</th>
                <th>Retrieval / Exec</th>
                <th>Candidates Considered</th>
              </tr>
            </thead>
            <tbody>
              {trace.traces.map((t) => (
                <tr key={t.step}>
                  <td className="mono">{t.step}</td>
                  <td>
                    <span className={`pill ${t.action === "tool_called" ? "ok" : "warn"}`}>
                      {t.action}
                    </span>
                  </td>
                  <td>
                    <div className="mono">{t.tool_name}</div>
                    <div className="muted">{t.domain}</div>
                  </td>
                  <td className="mono">{JSON.stringify(t.extracted_params)}</td>
                  <td className="mono">
                    {t.retrieval_latency_ms ?? "-"} ms / {t.execution_ms ?? "-"} ms
                  </td>
                  <td className="mono">
                    {(t.candidates_considered || [])
                      .map((c) => `${c.name}(${c.final_score})`)
                      .join(", ") || "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Send a message in Agent Chat to see live per-turn traces here.</p>
        )}
      </div>
    </div>
  );
}

