import React, { useEffect, useState } from "react";
import { Database, Cpu, ShieldCheck, RefreshCw, RotateCcw, KeyRound } from "lucide-react";
import { api, getAuthConfig, setAuthConfig } from "../../api";

export default function SettingsPanel({ sessionId, health, onNewSession, onRefreshHealth }) {
  const [obs, setObs] = useState(null);
  const [loading, setLoading] = useState(false);
  const [authCfg, setLocalAuthCfg] = useState(() => getAuthConfig());
  const [authStatus, setAuthStatus] = useState("");

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
    try {
      await api.resetCircuitBreakers();
      await loadSettingsData();
    } catch (err) {
      setAuthStatus(`Error: ${err.message}`);
    }
  };

  const handleApplyWorkspace = async () => {
    const cleanTenant = (authCfg.tenantId || "default").trim() || "default";
    setAuthConfig({ tenantId: cleanTenant, role: authCfg.role, token: "" });
    setLocalAuthCfg({ tenantId: cleanTenant, role: authCfg.role, token: "" });
    onNewSession?.();
    setAuthStatus(`Switched to tenant '${cleanTenant}' with role '${authCfg.role}' (fresh session started).`);
    await loadSettingsData();
  };

  const handleIssueToken = async () => {
    try {
      const cleanTenant = (authCfg.tenantId || "default").trim() || "default";
      const res = await api.issueToken("ui-user", cleanTenant, authCfg.role);
      setAuthConfig({ tenantId: cleanTenant, role: authCfg.role, token: res.access_token });
      setLocalAuthCfg({ tenantId: cleanTenant, role: authCfg.role, token: res.access_token });
      onNewSession?.();
      setAuthStatus(`Issued HS256 JWT for tenant='${res.tenant_id}', role='${res.role}'.`);
      await loadSettingsData();
    } catch (err) {
      setAuthStatus(`JWT Error: ${err.message}`);
    }
  };

  const handleClearToken = async () => {
    setAuthConfig({ token: "" });
    setLocalAuthCfg((prev) => ({ ...prev, token: "" }));
    setAuthStatus("Cleared JWT token (using workspace dev headers).");
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
                <td className="muted">Gemini LLM Reasoner</td>
                <td className="mono">
                  {obs?.gemini_llm?.configured
                    ? `Configured (${obs.gemini_llm.model})`
                    : `Heuristic Fallback (${obs?.gemini_llm?.model || "gemini-2.5-flash-lite"} key unset)`}
                </td>
              </tr>
              <tr>
                <td className="muted">PostgreSQL Vector Index</td>
                <td className="mono">pgvector HALFVEC(2560) · HNSW + GIN FTS</td>
              </tr>
              <tr>
                <td className="muted">Vectors Stored in DB</td>
                <td className="mono">
                  {obs?.embedding?.vectors_stored
                    ? `${obs.embedding.vectors_stored.tools} tools · ${obs.embedding.vectors_stored.kb_chunks} KB chunks`
                    : "-"}
                </td>
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
          <KeyRound size={17} color="var(--accent)" /> Multi-Tenant Workspace, RBAC &amp; Checkpoint Persistence
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 12, alignItems: "end" }}>
          <div>
            <label className="stat-label" style={{ display: "block", marginBottom: 4 }}>Tenant Workspace ID</label>
            <input
              className="input"
              value={authCfg.tenantId}
              onChange={(e) => setLocalAuthCfg((p) => ({ ...p, tenantId: e.target.value }))}
              placeholder="default"
            />
          </div>
          <div>
            <label className="stat-label" style={{ display: "block", marginBottom: 4 }}>RBAC Role</label>
            <select
              className="input"
              value={authCfg.role}
              onChange={(e) => setLocalAuthCfg((p) => ({ ...p, role: e.target.value }))}
            >
              <option value="finance_vp">finance_vp (PO &gt; $25k + tools)</option>
              <option value="operator">operator (standard tools, PO &lt;= $25k)</option>
              <option value="viewer">viewer (read-only RAG &amp; lookup)</option>
              <option value="admin">admin (full access)</option>
            </select>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button type="button" className="btn primary" onClick={handleApplyWorkspace}>
              Apply Workspace
            </button>
            <button type="button" className="btn" onClick={handleIssueToken}>
              Issue Demo JWT
            </button>
            {authCfg.token && (
              <button type="button" className="btn" onClick={handleClearToken}>
                Clear JWT
              </button>
            )}
          </div>
        </div>
        <div className="muted" style={{ marginTop: 10, fontSize: "0.86rem" }}>
          Checkpointer: <strong className="mono">{health?.checkpointer || obs?.security?.checkpointer || "postgres"}</strong> ·{" "}
          Auth Required: <strong className="mono">{String(obs?.security?.auth_required ?? health?.auth_required ?? false)}</strong> ·{" "}
          Rate Limit: <strong className="mono">{health?.rate_limit_rpm ?? obs?.security?.rate_limit_rpm ?? 120}/min</strong> ·{" "}
          Bearer JWT: <strong className="mono">{authCfg.token ? "Active" : "None (dev headers)"}</strong>
        </div>
        {authStatus && (
          <div style={{ marginTop: 8, fontSize: "0.86rem", color: authStatus.includes("Error") ? "var(--red)" : "var(--green)" }}>
            {authStatus}
          </div>
        )}
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

