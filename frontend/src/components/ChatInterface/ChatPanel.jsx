import React, { useEffect, useState } from "react";
import {
  Send,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  Sparkles,
  FileText,
  ChevronDown,
  ChevronUp,
  GitBranch,
  Clock,
} from "lucide-react";
import { api } from "../../api";

const DEMO_PROMPTS = [
  { label: "Test #1: Send invoice_001 to Mike", text: "send this invoice_001 invoice to mike" },
  { label: "Get Mike's Already-Sent Invoice", text: "get me the mike invoice already sent" },
  { label: "Test #2: Supplier SLA (PDF RAG)", text: "What does our supplier SLA say about delivery penalties?" },
  { label: "Test #3: Purchase Order (DOCX)", text: "Approve purchase order PO-2026-0188" },
  { label: "Test #4: Dispute Evidence", text: "Is there an open dispute from user_123?" },
  { label: "Test #5: Sales Analytics", text: "What was my total sales volume last month?" },
  { label: "Send Payment (HITL Gate)", text: "Send $500 to john@example.com" },
  { label: "System Search (Tools)", text: "What tools are available for managing invoices?" },
];

export default function ChatPanel({ sessionId, onTurnComplete, initialPrompt, onPromptConsumed }) {
  const [messages, setMessages] = useState([
    {
      id: "welcome",
      role: "assistant",
      text: "Hello! I'm ProcureIQ. Ask me to send payments, manage invoices or POs, look up disputes, inspect available tools, or query uploaded policy documents.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [requireHitl, setRequireHitl] = useState(true);
  const [confirmAll, setConfirmAll] = useState(false);
  const [expandedTools, setExpandedTools] = useState({});
  const [expandedSteps, setExpandedSteps] = useState({});
  const [editedParamsByMsg, setEditedParamsByMsg] = useState({});

  useEffect(() => {
    if (initialPrompt) {
      setInput(initialPrompt);
      onPromptConsumed?.();
    }
  }, [initialPrompt]);

  const appendMessage = (msg) =>
    setMessages((prev) => [...prev, { id: `${Date.now()}-${Math.random()}`, ...msg }]);

  const handleSend = async (customText) => {
    const text = (customText ?? input).trim();
    if (!text || loading) return;
    if (!customText) setInput("");

    appendMessage({ role: "user", text });
    setLoading(true);
    try {
      const res = await api.sendChat(text, sessionId, requireHitl, confirmAll);
      appendMessage({
        role: "assistant",
        text: res.response,
        meta: res,
      });
      onTurnComplete?.();
    } catch (err) {
      appendMessage({
        role: "assistant",
        text: `Error: ${err.message}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (msgId, approved, baseParams = {}) => {
    if (loading) return;
    setLoading(true);
    try {
      const mergedParams =
        approved && baseParams && Object.keys(baseParams).length > 0
          ? { ...baseParams, ...(editedParamsByMsg[msgId] || {}) }
          : null;
      const res = await api.confirmAction(sessionId, approved, mergedParams);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? { ...m, meta: { ...m.meta, requires_confirmation: false, resolved: approved ? "approved" : "cancelled" } }
            : m
        )
      );
      appendMessage({
        role: "assistant",
        text: res.response,
        meta: res,
      });
      onTurnComplete?.();
    } catch (err) {
      appendMessage({
        role: "assistant",
        text: `Confirmation error: ${err.message}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const toggleExpand = (id) =>
    setExpandedTools((prev) => ({ ...prev, [id]: !prev[id] }));

  const toggleSteps = (id, currentlyOpen) =>
    setExpandedSteps((prev) => ({ ...prev, [id]: !currentlyOpen }));

  return (
    <div className="chat-layout">
      <div className="chat-box">
        <div className="chat-messages">
          {messages.map((m, idx) => {
            const meta = m.meta;
            const isExpanded = !!expandedTools[m.id];
            const hasSteps = meta?.execution_steps?.length > 0;
            const stepsExpanded = expandedSteps[m.id] ?? (idx === messages.length - 1);
            return (
              <div key={m.id} className={`msg-row ${m.role}`}>
                <div className="msg-bubble">{m.text}</div>

                {meta && (
                  <div className="msg-meta">
                    {meta.domain && <span className="pill accent">domain: {meta.domain}</span>}
                    {meta.tool_used && <span className="pill purple">tool: {meta.tool_used}</span>}
                    {meta.retrieval_latency_ms != null && (
                      <span className="pill">{meta.retrieval_latency_ms} ms</span>
                    )}
                    {meta.extracted_params && Object.keys(meta.extracted_params).length > 0 && (
                      <span className="pill mono">
                        params: {JSON.stringify(meta.extracted_params)}
                      </span>
                    )}
                    {meta.retrieved_tools?.length > 0 && (
                      <button
                        type="button"
                        className="pill"
                        style={{ cursor: "pointer" }}
                        onClick={() => toggleExpand(m.id)}
                      >
                        Top-{meta.retrieved_tools.length} Tool RAG{" "}
                        {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      </button>
                    )}
                    {hasSteps && (
                      <button
                        type="button"
                        className="pill"
                        style={{ cursor: "pointer" }}
                        onClick={() => toggleSteps(m.id, stepsExpanded)}
                      >
                        <GitBranch size={12} /> Steps ({meta.execution_steps.length}){" "}
                        {stepsExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      </button>
                    )}
                  </div>
                )}

                {meta && isExpanded && meta.retrieved_tools?.length > 0 && (
                  <div
                    className="card"
                    style={{ marginTop: 8, padding: 10, width: "100%", fontSize: "0.8rem" }}
                  >
                    <div className="muted" style={{ marginBottom: 6 }}>
                      Retrieved by Hybrid Tool RAG (bound strictly to top-{meta.retrieved_tools.length}):
                    </div>
                    {meta.retrieved_tools.map((t, idx) => (
                      <div
                        key={t.name}
                        style={{ display: "flex", justifyContent: "space-between", padding: "3px 0" }}
                      >
                        <span className="mono">
                          #{idx + 1} {t.name} ({t.domain})
                        </span>
                        <span className="mono" style={{ color: "var(--accent)" }}>
                          score: {t.final_score}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {meta && stepsExpanded && hasSteps && (
                  <div className="step-timeline">
                    <div className="muted" style={{ fontSize: "0.76rem", fontWeight: 600 }}>
                      LangGraph Execution Pipeline
                    </div>
                    {meta.execution_steps.map((s, sIdx) => (
                      <div key={`${m.id}-step-${sIdx}`} className="step-row">
                        <span className={`step-dot ${s.status || "completed"}`} />
                        <div className="step-body">
                          <div className="step-head">
                            <span>
                              <strong>{sIdx + 1}. {s.title || s.node}</strong>{" "}
                              <span className="pill" style={{ fontSize: "0.68rem", padding: "1px 6px" }}>
                                {s.status || "completed"}
                              </span>
                            </span>
                            <span className="muted mono" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                              <Clock size={11} /> {s.duration_ms ?? 0} ms
                            </span>
                          </div>
                          <div className="step-detail">{s.detail}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {meta?.requires_confirmation && meta?.pending_action && (
                  <div className="hitl-card">
                    <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600 }}>
                      <ShieldAlert size={16} color="#f59e0b" />
                      Human-in-the-Loop Confirmation Required
                    </div>
                    <div className="muted" style={{ marginTop: 4 }}>
                      Action: <span className="mono">{meta.pending_action.tool}</span>
                      {meta.pending_action.domain ? ` (${meta.pending_action.domain})` : ""}
                    </div>
                    {meta.pending_action.reason && (
                      <div className="muted" style={{ marginTop: 3, fontSize: "0.79rem" }}>
                        <strong>Tool Choice:</strong> {meta.pending_action.reason}
                      </div>
                    )}
                    {meta.pending_action.kb_sources?.length > 0 && (
                      <div className="muted" style={{ marginTop: 2, fontSize: "0.79rem" }}>
                        <strong>KB Docs:</strong> {meta.pending_action.kb_sources.join(", ")}
                      </div>
                    )}
                    {meta.pending_action.params && Object.keys(meta.pending_action.params).length > 0 ? (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                        {Object.entries(meta.pending_action.params).map(([k, v]) => (
                          <label key={k} style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: "0.75rem" }}>
                            <span className="muted mono">{k}</span>
                            <input
                              className="text-input mono"
                              style={{ padding: "4px 8px", fontSize: "0.78rem", minWidth: 150 }}
                              value={editedParamsByMsg[m.id]?.[k] ?? String(v ?? "")}
                              onChange={(e) =>
                                setEditedParamsByMsg((prev) => ({
                                  ...prev,
                                  [m.id]: { ...(prev[m.id] || {}), [k]: e.target.value },
                                }))
                              }
                            />
                          </label>
                        ))}
                      </div>
                    ) : (
                      <div className="muted mono" style={{ marginTop: 4, fontSize: "0.78rem" }}>
                        Parameters: {"{}"}
                      </div>
                    )}
                    <div className="hitl-actions">
                      <button
                        type="button"
                        className="btn btn-approve"
                        disabled={loading}
                        onClick={() => handleConfirm(m.id, true, meta.pending_action.params || {})}
                      >
                        <CheckCircle2 size={15} /> Approve &amp; Execute
                      </button>
                      <button
                        type="button"
                        className="btn btn-cancel"
                        disabled={loading}
                        onClick={() => handleConfirm(m.id, false)}
                      >
                        <XCircle size={15} /> Cancel
                      </button>
                    </div>
                  </div>
                )}

                {meta?.sources?.length > 0 && (
                  <div className="card" style={{ marginTop: 8, padding: 10, width: "100%" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.82rem", fontWeight: 600 }}>
                      <FileText size={14} /> Knowledge Base Sources
                    </div>
                    {meta.sources.slice(0, 3).map((s, idx) => (
                      <div key={idx} className="muted" style={{ marginTop: 6, fontSize: "0.78rem" }}>
                        <strong>{s.document}</strong> (p.{s.page || 1}): {s.excerpt}...
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {loading && <div className="muted">Agent thinking...</div>}
        </div>

        <form
          className="chat-input-bar"
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
        >
          <input
            className="text-input"
            style={{ flex: 1 }}
            placeholder="Ask ProcureIQ (e.g. 'Send $500 to john@example.com' or 'What tools handle invoices?')"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={loading}
          />
          <button type="submit" className="btn btn-primary" disabled={loading || !input.trim()}>
            <Send size={15} /> Send
          </button>
        </form>
      </div>

      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10, overflowY: "auto" }}>
        <h3 className="card-title">
          <Sparkles size={16} color="#38bdf8" /> Interview Demo Prompts
        </h3>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.82rem", color: "var(--text-muted)" }}>
          <input
            type="checkbox"
            checked={requireHitl}
            onChange={(e) => setRequireHitl(e.target.checked)}
          />
          Require HITL confirmation on writes
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.82rem", color: "var(--text-muted)" }}>
          <input
            type="checkbox"
            checked={confirmAll}
            disabled={!requireHitl}
            onChange={(e) => setConfirmAll(e.target.checked)}
          />
          Ask confirm on all tools (read + write)
        </label>
        {DEMO_PROMPTS.map((p) => (
          <button
            key={p.label}
            type="button"
            className="demo-chip"
            disabled={loading}
            onClick={() => handleSend(p.text)}
          >
            <div style={{ fontWeight: 600, color: "var(--accent)", marginBottom: 2 }}>{p.label}</div>
            <div className="muted">{p.text}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

