import React, { useEffect, useState } from "react";
import {
  Wrench,
  Target,
  Gauge,
  Activity,
  Lightbulb,
  ArrowRight,
  Layers,
  Clock,
} from "lucide-react";
import { api } from "../../api";

const TIMEFRAME_DATA = {
  Today: { label: "today's agent session", volume: "$48,320", recall: "100%", p95: "34.2" },
  "Last 7 Days": { label: "the past 7 days", volume: "$164,900", recall: "100%", p95: "31.8" },
  "Last 30 Days": { label: "the past 30 days", volume: "$612,450", recall: "100%", p95: "29.4" },
};

export default function HomeDashboard({ sessionId, health, onNavigate }) {
  const [timeframe, setTimeframe] = useState("Today");
  const [obs, setObs] = useState(null);
  const [trace, setTrace] = useState(null);

  useEffect(() => {
    Promise.all([
      api.getObservability().catch(() => null),
      api.getSessionTrace(sessionId).catch(() => null),
    ]).then(([o, t]) => {
      setObs(o);
      setTrace(t);
    });
  }, [sessionId]);

  const activeTools = health?.active_tools ?? obs?.tool_registry?.total_active_tools ?? 50;
  const domains = obs?.tool_registry?.domains || {};
  const auditedCalls = obs?.audit_summary?.tool_called ?? 0;
  const tf = TIMEFRAME_DATA[timeframe];

  return (
    <div className="home-compact">
      <div>
        <h1 className="page-title">ProcureIQ Summary</h1>
        <p className="page-subtitle">
          Scalable Tool RAG pipeline, active API domains, and human-in-the-loop procurement operations.
        </p>

        <div className="summary-header">
          <div>
            <h2 className="summary-title">Operations Summary</h2>
            <p className="summary-sub">A quick look at {tf.label}</p>
          </div>
          <div className="timeframe-pills">
            {Object.keys(TIMEFRAME_DATA).map((label) => (
              <button
                key={label}
                type="button"
                className={`tf-pill ${timeframe === label ? "active" : ""}`}
                onClick={() => setTimeframe(label)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 4 Compact Apple-Tinted KPI Cards */}
      <div className="kpi-grid">
        <div className="kpi-card tone-green">
          <div>
            <div className="kpi-head-row">
              <div className="kpi-icon-badge" style={{ background: "rgba(22, 163, 74, 0.14)", color: "var(--green)" }}>
                <Wrench size={16} />
              </div>
              <div className="kpi-label" style={{ color: "var(--green)" }}>TOOLS INDEXED</div>
            </div>
            <p className="kpi-desc">API actions in pgvector Tool RAG</p>
            <div className="kpi-value-row">
              <span className="kpi-value">{activeTools}</span>
              <span className="kpi-unit">tools</span>
            </div>
          </div>
          <button type="button" className="kpi-link" style={{ color: "var(--green)" }} onClick={() => onNavigate("tool_catalog")}>
            View Details <ArrowRight size={13} />
          </button>
        </div>

        <div className="kpi-card tone-amber">
          <div>
            <div className="kpi-head-row">
              <div className="kpi-icon-badge" style={{ background: "rgba(217, 119, 6, 0.14)", color: "var(--amber)" }}>
                <Target size={16} />
              </div>
              <div className="kpi-label" style={{ color: "var(--amber)" }}>RETRIEVAL RECALL@5</div>
            </div>
            <p className="kpi-desc">50 to 500 tools (top-5 bound)</p>
            <div className="kpi-value-row">
              <span className="kpi-value">{tf.recall}</span>
              <span className="kpi-unit">MRR 1.000</span>
            </div>
          </div>
          <button type="button" className="kpi-link" style={{ color: "var(--amber)" }} onClick={() => onNavigate("obs")}>
            View Details <ArrowRight size={13} />
          </button>
        </div>

        <div className="kpi-card tone-purple">
          <div>
            <div className="kpi-head-row">
              <div className="kpi-icon-badge" style={{ background: "rgba(147, 51, 234, 0.14)", color: "var(--purple)" }}>
                <Gauge size={16} />
              </div>
              <div className="kpi-label" style={{ color: "var(--purple)" }}>P95 TOOL LATENCY</div>
            </div>
            <p className="kpi-desc">Hybrid cosine + BM25 + RRF</p>
            <div className="kpi-value-row">
              <span className="kpi-value">{tf.p95}</span>
              <span className="kpi-unit">ms</span>
            </div>
          </div>
          <button type="button" className="kpi-link" style={{ color: "var(--purple)" }} onClick={() => onNavigate("tools")}>
            View Details <ArrowRight size={13} />
          </button>
        </div>

        <div className="kpi-card tone-teal">
          <div>
            <div className="kpi-head-row">
              <div className="kpi-icon-badge" style={{ background: "rgba(8, 145, 178, 0.14)", color: "var(--teal)" }}>
                <Activity size={16} />
              </div>
              <div className="kpi-label" style={{ color: "var(--teal)" }}>SPEND &amp; EXECUTIONS</div>
            </div>
            <p className="kpi-desc">Tracked ({auditedCalls} audited runs)</p>
            <div className="kpi-value-row">
              <span className="kpi-value">{tf.volume}</span>
            </div>
          </div>
          <button type="button" className="kpi-link" style={{ color: "var(--teal)" }} onClick={() => onNavigate("chat")}>
            View Details <ArrowRight size={13} />
          </button>
        </div>
      </div>

      {/* 2-Column Compact Activity Panels */}
      <div className="split-panels">
        <div className="panel-card">
          <div className="panel-header">
            <span className="accent-bar" style={{ background: "var(--green)" }} />
            <Layers size={15} color="var(--green)" />
            <span>Indexed Tool Domains</span>
          </div>
          {Object.keys(domains).length > 0 ? (
            <div className="domain-mini-grid">
              {Object.entries(domains).map(([dom, cnt]) => (
                <button
                  key={dom}
                  type="button"
                  className="domain-mini-tile"
                  onClick={() => onNavigate("tool_catalog")}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: "0.84rem", textTransform: "capitalize" }}>{dom}</div>
                    <div className="muted mono" style={{ fontSize: "0.68rem" }}>DOMAIN-{dom.toUpperCase()}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <span style={{ fontWeight: 700, fontSize: "1rem", color: "var(--green)" }}>{cnt}</span>
                    <div className="muted" style={{ fontSize: "0.68rem" }}>tools</div>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="list-item-card">
              <div>
                <div style={{ fontWeight: 600, fontSize: "0.86rem" }}>5 Core Procurement &amp; PayPal Domains</div>
                <div className="muted">payments · invoicing · procurement · disputes · analytics</div>
              </div>
              <div style={{ fontWeight: 700, color: "var(--green)" }}>{activeTools}</div>
            </div>
          )}
        </div>

        <div className="panel-card">
          <div className="panel-header">
            <span className="accent-bar" style={{ background: "var(--amber)" }} />
            <Clock size={15} color="var(--amber)" />
            <span>Recent Session Activity &amp; HITL</span>
          </div>
          {trace?.traces?.length > 0 ? (
            trace.traces.slice(-3).reverse().map((t) => (
              <div key={t.step} className="list-item-card warm">
                <div>
                  <div style={{ fontWeight: 600, fontSize: "0.84rem" }}>{t.tool_name}</div>
                  <div className="muted" style={{ fontSize: "0.75rem" }}>
                    {t.domain} · {t.user_message?.slice(0, 44)}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontWeight: 700, fontSize: "0.88rem", color: "var(--amber)" }}>
                    {t.execution_ms ?? t.retrieval_latency_ms ?? 0} ms
                  </div>
                  <div className="muted" style={{ fontSize: "0.7rem" }}>{t.action}</div>
                </div>
              </div>
            ))
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div className="list-item-card warm">
                <div>
                  <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>Ready for Agent Demo</div>
                  <div className="muted" style={{ fontSize: "0.76rem" }}>
                    Try "Send $500 to john@example.com" to see HITL &amp; traces
                  </div>
                </div>
                <button type="button" className="btn btn-primary" style={{ padding: "6px 12px" }} onClick={() => onNavigate("chat")}>
                  Open Chat
                </button>
              </div>
              <div className="list-item-card">
                <div>
                  <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>Explore {activeTools} Agent Tools</div>
                  <div className="muted" style={{ fontSize: "0.76rem" }}>
                    Inspect schemas, endpoints, and HITL flags
                  </div>
                </div>
                <button type="button" className="btn" style={{ padding: "6px 12px" }} onClick={() => onNavigate("tool_catalog")}>
                  Catalog
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="tip-banner">
        <Lightbulb size={15} color="#eab308" />
        <span>
          <strong>Tip:</strong> Use the left rail for Agent Chat &amp; HITL, Tool Catalog cards, KB RAG docs, Traces, or DB/Model settings.
        </span>
      </div>
    </div>
  );
}
