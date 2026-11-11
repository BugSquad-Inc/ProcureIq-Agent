import React, { useEffect, useState } from "react";
import { Database, Cpu, ShieldCheck, RefreshCw, RotateCcw } from "lucide-react";
import { api } from "../../api";

export default function SettingsPanel({ sessionId, health, onNewSession, onRefreshHealth }) {
  const [obs, setObs] = useState(null);
  const [loading, setLoading] = useState(false);

  const loadSettingsData = async () => {
    setLoading(true);
    try {
      await onRefreshHealth?.();
      const o = await api.getObservability();
      setObs(o);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettingsData();
  }, []);

  const handleResetBreakers = async () => {
    await api.resetCircuitBreakers();
    await loadSettingsData();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <div>
          <h1 className="page-title" style={{ marginBottom: 2 }}>System Settings &amp; Infrastructure</h1>
          <p className="page-subtitle" style={{ marginBottom: 0 }}>
            Database connection, active embedding model, session state, and circuit breakers.
          </p>
        </div>
        <button type="button" className="btn" onClick={loadSettingsData} disabled={loading}>
          <RefreshCw size={14} /> Refresh Status
        </button>
      </div>

      <div className="grid-4">
        <div className="stat-box">
          <div className="stat-label">Database Status</div>
          <div className="stat-val" style={{ fontSize: "1.15rem", color: health?.database === "connected" ? "var(--green)" : "var(--amber)" }}>
            {health?.database || "unknown"}
          </div>
        </div>
        <div className="stat-box">
          <div className="stat-label">Active Tools Bound</div>
          <div className="stat-val">{health?.active_tools ?? obs?.tool_registry?.total_active_tools ?? 0}</div>
        </div>
        <div className="stat-box">
          <div className="stat-label">Target Vector Dim</div>
          <div className="stat-val">{health?.target_dimension ?? obs?.embedding?.target_dimension ?? 2560}d</div>
        </div>
        <div className="stat-box">
          <div className="stat-label">LangSmith Tracing</div>
          <div className="stat-val" style={{ fontSize: "1.1rem" }}>
            {obs?.langsmith?.enabled ? "Enabled" : "Local Mode"}
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3 className="card-title">
            <Cpu size={17} color="var(--accent)" /> Embedding &amp; Vector Configuration
          </h3>
          <table className="data-table">
            <tbody>
              <tr>
                <td className="muted">Configured Provider</td>
                <td className="mono">{health?.embedding_provider || obs?.embedding?.configured_provider || "qwen"}</td>
              </tr>
              <tr>
                <td className="muted">Active Model</td>
                <td className="mono">{health?.embedding_model || obs?.embedding?.active_model || "-"}</td>
              </tr>
              <tr>
                <td className="muted">PostgreSQL Vector Index</td>
                <td className="mono">pgvector HALFVEC(2560) · HNSW + GIN FTS</td>
              </tr>
              <tr>
                <td className="muted">Current Session ID</td>
                <td className="mono">{sessionId}</td>
              </tr>
            </tbody>
          </table>
          <div style={{ marginTop: 12 }}>
            <button type="button" className="btn" onClick={onNewSession}>
              <RotateCcw size={14} /> Start Fresh Session
            </button>
          </div>
        </div>

        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <h3 className="card-title" style={{ margin: 0 }}>
              <ShieldCheck size={17} color="var(--green)" /> Circuit Breakers
            </h3>
            <button type="button" className="btn" onClick={handleResetBreakers}>
              Reset Breakers
            </button>
          </div>
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
            <p className="muted">All adapters healthy (no failures recorded in this runtime).</p>
          )}
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">
          <Database size={17} color="var(--purple)" /> Knowledge Base &amp; Audit Telemetry
        </h3>
        <div className="muted">
          KB Chunks Indexed: <strong className="mono">{obs?.knowledge_base?.total_chunks ?? 0}</strong> ·{" "}
          Audited Tool Calls: <strong className="mono">{obs?.audit_summary?.tool_called ?? 0}</strong> ·{" "}
          Cancelled Actions: <strong className="mono">{obs?.audit_summary?.action_cancelled ?? 0}</strong> ·{" "}
          Failed Actions: <strong className="mono">{obs?.audit_summary?.tool_failed ?? 0}</strong>
        </div>
      </div>
    </div>
  );
}

