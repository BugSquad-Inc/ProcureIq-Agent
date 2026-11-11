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
} from "lucide-react";
import { api } from "../../api";

const DEMO_PROMPTS = [
  { label: "Send Payment (HITL Gate)", text: "Send $500 to john@example.com" },
  { label: "Sales Analytics", text: "What was my total sales volume last month?" },
  { label: "Dispute Lookup", text: "Is there an open dispute from user_123?" },
  { label: "Create PO (HITL Gate)", text: "Create a purchase order for $45,000 to Acme Corp for server hardware" },
  { label: "System Search (Tools)", text: "What tools are available for managing invoices?" },
  { label: "System Search (History)", text: "What was the status of my last request?" },
  { label: "RAG Knowledge Base", text: "What does our supplier SLA say about delivery penalties?" },
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
  const [expandedTools, setExpandedTools] = useState({});

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
      const res = await api.sendChat(text, sessionId, requireHitl);
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

  const handleConfirm = async (msgId, approved) => {
    if (loading) return;
    setLoading(true);
    try {
      const res = await api.confirmAction(sessionId, approved);
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

  return (
    <div className="chat-layout">
      <div className="chat-box">
        <div className="chat-messages">
          {messages.map((m) => {
            const meta = m.meta;
            const isExpanded = !!expandedTools[m.id];
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

                {meta?.requires_confirmation && meta?.pending_action && (
                  <div className="hitl-card">
                    <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600 }}>
                      <ShieldAlert size={16} color="#f59e0b" />
                      Human-in-the-Loop Confirmation Required
                    </div>
                    <div className="muted" style={{ marginTop: 4 }}>
                      Action: <span className="mono">{meta.pending_action.tool}</span> · Parameters:{" "}
                      <span className="mono">{JSON.stringify(meta.pending_action.params)}</span>
                    </div>
                    <div className="hitl-actions">
                      <button
                        type="button"
                        className="btn btn-approve"
                        disabled={loading}
                        onClick={() => handleConfirm(m.id, true)}
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

