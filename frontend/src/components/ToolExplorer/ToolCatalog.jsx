import React, { useEffect, useMemo, useState } from "react";
import {
  Search,
  Wrench,
  ShieldAlert,
  Eye,
  X,
  ArrowRight,
  Code2,
  Globe,
  Cpu,
  CheckCircle2,
} from "lucide-react";
import { api } from "../../api";

const WRITE_TOOL_NAMES = new Set([
  "send_payment", "create_order", "capture_order", "refund_payment", "authorize_payment",
  "create_payout_batch", "create_subscription_plan", "cancel_subscription",
  "create_invoice", "send_invoice", "cancel_invoice", "remind_invoice",
  "record_invoice_payment", "flag_invoice_discrepancy", "create_product",
  "accept_dispute_claim", "provide_dispute_evidence", "escalate_dispute",
  "create_purchase_order", "approve_purchase_order", "cancel_purchase_order",
  "create_vendor", "submit_goods_receipt", "create_rfq",
]);

const BUILTIN_TOOLS = [
  {
    id: "builtin-rag",
    name: "rag_query",
    domain: "rag",
    description:
      "Hybrid Retrieval-Augmented Generation pipeline over uploaded enterprise PDFs, DOCX, contracts, and supplier SLAs using pgvector HALFVEC + OR-BM25 + RRF.",
    schema: { query: "string" },
    endpoint: "internal:rag (kb_chunks)",
    is_active: true,
    is_builtin: true,
  },
  {
    id: "builtin-system",
    name: "system_search",
    domain: "system",
    description:
      "Introspects the agent's own Tool Registry capabilities and PostgreSQL audit_log execution history for the current conversation session.",
    schema: { query: "string", session_id: "string" },
    endpoint: "internal:system (tools + audit_log)",
    is_active: true,
    is_builtin: true,
  },
];

const DOMAIN_COLORS = {
  payments: { color: "var(--green)", bg: "var(--green-dim)" },
  invoicing: { color: "var(--accent)", bg: "var(--accent-dim)" },
  procurement: { color: "var(--amber)", bg: "var(--amber-dim)" },
  disputes: { color: "var(--red)", bg: "var(--red-dim)" },
  analytics: { color: "var(--purple)", bg: "var(--purple-dim)" },
  rag: { color: "var(--teal)", bg: "var(--accent-dim)" },
  system: { color: "var(--purple)", bg: "var(--purple-dim)" },
};

function getExamplePrompt(tool) {
  const examples = {
    send_payment: "Send $500 to john@example.com",
    create_invoice: "Create an invoice for $750 to client@example.com",
    send_invoice: "Send an invoice for $50 to client@example.com",
    get_sales_report: "What was my total sales volume last month?",
    get_dispute: "Is there an open dispute from user_123?",
    list_disputes: "List all open customer disputes",
    create_purchase_order: "Create a purchase order for $45,000 to Acme Corp for server hardware",
    approve_purchase_order: "Approve purchase order PO-2026-0188",
    get_balance: "Check current available PayPal account balance",
    refund_payment: "Issue a refund of $120 for a customer payment",
    rag_query: "What does our supplier SLA say about delivery penalties?",
    system_search: "What tools are available for managing invoices?",
  };
  if (examples[tool.name]) return examples[tool.name];
  const readable = tool.name.replace(/_/g, " ");
  return `Run ${readable} for my procurement workspace`;
}

export default function ToolCatalog({ onTryPrompt, onOpenRagExplorer }) {
  const [catalog, setCatalog] = useState({ total: 0, domains: {}, tools: [] });
  const [domainFilter, setDomainFilter] = useState("all");
  const [searchText, setSearchText] = useState("");
  const [selectedTool, setSelectedTool] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    api
      .getTools("", "")
      .then((data) => setCatalog(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const allTools = useMemo(
    () => [...catalog.tools, ...BUILTIN_TOOLS],
    [catalog.tools]
  );

  const domainCounts = useMemo(() => {
    const counts = { ...(catalog.domains || {}), rag: 1, system: 1 };
    return counts;
  }, [catalog.domains]);

  const filteredTools = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    return allTools.filter((t) => {
      if (domainFilter !== "all" && t.domain !== domainFilter) return false;
      if (!q) return true;
      return (
        t.name.toLowerCase().includes(q) ||
        t.domain.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q)
      );
    });
  }, [allTools, domainFilter, searchText]);

  return (
    <div>
      <div className="summary-header" style={{ marginBottom: 16 }}>
        <div>
          <h1 className="page-title" style={{ marginBottom: 4 }}>Agent Tool Catalog</h1>
          <p className="page-subtitle" style={{ marginBottom: 0 }}>
            Click any tool card to inspect what it does, its parameter schema, HITL safety level, and example prompts.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={onOpenRagExplorer}>
          <Cpu size={15} /> Test Tool RAG Retrieval
        </button>
      </div>

      {/* Filter Toolbar */}
      <div className="card" style={{ marginBottom: 16, padding: "14px 16px" }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
          <div style={{ position: "relative", flex: 1, minWidth: 240 }}>
            <Search
              size={15}
              style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)" }}
            />
            <input
              className="text-input"
              style={{ width: "100%", paddingLeft: 34 }}
              placeholder="Search 52 agent tools by name, action, or description..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
            />
          </div>
          <span className="muted mono">
            Showing {filteredTools.length} of {allTools.length} tools
          </span>
        </div>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button
            type="button"
            className={`tf-pill ${domainFilter === "all" ? "active" : ""}`}
            onClick={() => setDomainFilter("all")}
          >
            All ({allTools.length})
          </button>
          {Object.entries(domainCounts).map(([dom, cnt]) => (
            <button
              key={dom}
              type="button"
              className={`tf-pill ${domainFilter === dom ? "active" : ""}`}
              onClick={() => setDomainFilter(dom)}
              style={{ textTransform: "capitalize" }}
            >
              {dom} ({cnt})
            </button>
          ))}
        </div>
      </div>

      {error && <p style={{ color: "var(--red)" }}>{error}</p>}
      {loading && <p className="muted">Loading tool catalog...</p>}

      {/* Tool Cards Grid */}
      <div className="tool-cards-grid">
        {filteredTools.map((tool) => {
          const isWrite = WRITE_TOOL_NAMES.has(tool.name);
          const theme = DOMAIN_COLORS[tool.domain] || { color: "var(--accent)", bg: "var(--accent-dim)" };
          const paramCount = Object.keys(tool.schema || {}).length;
          return (
            <button
              key={tool.id || tool.name}
              type="button"
              className={`tool-card domain-${tool.domain}`}
              onClick={() => setSelectedTool(tool)}
            >
              <div className="tool-card-top">
                <span
                  className="pill"
                  style={{
                    color: theme.color,
                    background: "var(--badge-glass)",
                    borderColor: "var(--border)",
                    fontWeight: 700,
                    textTransform: "uppercase",
                    fontSize: "0.66rem",
                  }}
                >
                  {tool.domain}
                </span>
                <span
                  className={`pill ${isWrite ? "warn" : "ok"}`}
                  style={{ fontSize: "0.66rem", fontWeight: 600 }}
                >
                  {isWrite ? "HITL Write" : "Read-Only"}
                </span>
              </div>

              <div className="tool-card-name mono">{tool.name}</div>
              <p className="tool-card-desc">{tool.description}</p>

              <div className="tool-card-footer">
                <span className="muted mono">{paramCount} param{paramCount === 1 ? "" : "s"}</span>
                <span className="kpi-link" style={{ color: "var(--accent)", fontSize: "0.78rem" }}>
                  Details <ArrowRight size={13} />
                </span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Tool Details Modal */}
      {selectedTool && (
        <div className="modal-backdrop" onClick={() => setSelectedTool(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                  <span
                    className="pill"
                    style={{
                      color: (DOMAIN_COLORS[selectedTool.domain] || {}).color || "var(--accent)",
                      background: (DOMAIN_COLORS[selectedTool.domain] || {}).bg || "var(--accent-dim)",
                      borderColor: "transparent",
                      fontWeight: 700,
                      textTransform: "uppercase",
                    }}
                  >
                    {selectedTool.domain}
                  </span>
                  {WRITE_TOOL_NAMES.has(selectedTool.name) ? (
                    <span className="pill warn">
                      <ShieldAlert size={13} /> Write Operation · HITL Confirmation Required
                    </span>
                  ) : (
                    <span className="pill ok">
                      <CheckCircle2 size={13} /> Read-Only · Instant Execution
                    </span>
                  )}
                </div>
                <h2 className="mono" style={{ margin: 0, fontSize: "1.2rem" }}>
                  {selectedTool.name}
                </h2>
              </div>
              <button
                type="button"
                className="btn"
                style={{ padding: "6px 8px" }}
                onClick={() => setSelectedTool(null)}
                aria-label="Close tool details"
              >
                <X size={16} />
              </button>
            </div>

            <div className="modal-section">
              <div className="sidebar-section-title" style={{ paddingLeft: 0 }}>What This Tool Does</div>
              <p style={{ margin: "4px 0 0", fontSize: "0.94rem" }}>{selectedTool.description}</p>
            </div>

            <div className="modal-section">
              <div className="sidebar-section-title" style={{ paddingLeft: 0 }}>How the Agent Routes to It</div>
              <p className="muted" style={{ margin: "4px 0 0" }}>
                Indexed in PostgreSQL (<span className="mono">HALFVEC(2560)</span> + GIN full-text index).
                When a user asks a matching question, <span className="mono">ToolRetriever</span> ranks it in the
                top-5 candidates and binds only those 5 schemas to the LangGraph executor.
              </p>
            </div>

            <div className="modal-section">
              <div className="sidebar-section-title" style={{ paddingLeft: 0 }}>
                <Globe size={12} style={{ verticalAlign: "middle", marginRight: 4 }} />
                API Endpoint / Adapter Target
              </div>
              <div className="code-box mono">{selectedTool.endpoint || "internal:adapter"}</div>
            </div>

            <div className="modal-section">
              <div className="sidebar-section-title" style={{ paddingLeft: 0 }}>
                <Code2 size={12} style={{ verticalAlign: "middle", marginRight: 4 }} />
                Expected Parameters Schema
              </div>
              {Object.keys(selectedTool.schema || {}).length > 0 ? (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Parameter</th>
                      <th>Type</th>
                      <th>Extraction</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(selectedTool.schema).map(([k, v]) => (
                      <tr key={k}>
                        <td className="mono" style={{ fontWeight: 600 }}>{k}</td>
                        <td><span className="pill accent">{String(v)}</span></td>
                        <td className="muted">Extracted from chat message via LLM / entity parser</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="muted" style={{ margin: "4px 0 0" }}>No required parameters — runs directly from user intent.</p>
              )}
            </div>

            <div className="modal-section" style={{ marginBottom: 0 }}>
              <div className="sidebar-section-title" style={{ paddingLeft: 0 }}>Example User Prompt</div>
              <div className="code-box" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <span>"{getExamplePrompt(selectedTool)}"</span>
                {onTryPrompt && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => {
                      const prompt = getExamplePrompt(selectedTool);
                      setSelectedTool(null);
                      onTryPrompt(prompt);
                    }}
                  >
                    <Eye size={14} /> Try in Agent Chat
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

