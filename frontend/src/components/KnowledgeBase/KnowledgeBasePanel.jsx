import React, { useState } from "react";
import { Upload, FileText, Search } from "lucide-react";
import { api } from "../../api";

const SAMPLE_SLA = `Enterprise Supplier SLA & Procurement Policy (v2.1)

Section 4.2 — Delivery Penalties:
All approved hardware and server purchase orders must be delivered within 5 business days.
Late deliveries incur a 2% penalty per delayed business day, capped at 10% of total PO value.

Section 5.1 — Invoice Reconciliation & Payment Terms:
Standard supplier payment terms are Net 30 from receipt of a matched 3-way invoice (PO + Goods Receipt + Invoice).
Any price or quantity discrepancy exceeding 1.5% must be flagged via flag_invoice_discrepancy prior to settlement.

Section 6.3 — Dispute Escalation:
Counterparty disputes over $500 unresolved after 7 days must be escalated with supporting shipment documentation.`;

export default function KnowledgeBasePanel({ sessionId, onUploaded }) {
  const [uploadStatus, setUploadStatus] = useState("");
  const [uploading, setUploading] = useState(false);
  const [ragQuery, setRagQuery] = useState("What does our supplier SLA say about delivery penalties?");
  const [ragResponse, setRagResponse] = useState(null);
  const [querying, setQuerying] = useState(false);

  const handleFileUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    setUploadStatus("");
    try {
      const res = await api.uploadKBFile(file);
      setUploadStatus(`Ingested "${res.filename}" (${res.chunks_created} chunks indexed into pgvector).`);
      onUploaded?.();
    } catch (err) {
      setUploadStatus(`Upload failed: ${err.message}`);
    } finally {
      setUploading(false);
    }
  };

  const handleLoadSampleSLA = async () => {
    const blob = new Blob([SAMPLE_SLA], { type: "text/plain" });
    const file = new File([blob], "Enterprise_Supplier_SLA_v2.1.txt", { type: "text/plain" });
    await handleFileUpload(file);
  };

  const handleRagQuery = async (e) => {
    e.preventDefault();
    if (!ragQuery.trim()) return;
    setQuerying(true);
    try {
      const res = await api.sendChat(ragQuery.trim(), sessionId, false);
      setRagResponse(res);
    } catch (err) {
      setRagResponse({ response: `Error: ${err.message}`, sources: [] });
    } finally {
      setQuerying(false);
    }
  };

  return (
    <div className="grid-2">
      <div className="card">
        <h3 className="card-title">
          <Upload size={17} color="#38bdf8" /> Upload Knowledge Base Document
        </h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Upload PDF, DOCX, or TXT contracts/SOPs. Chunks are embedded into <span className="mono">kb_chunks</span>{" "}
          (<span className="mono">HALFVEC(2560)</span>) for Hybrid RAG search.
        </p>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="file"
            accept=".txt,.pdf,.docx,.md"
            disabled={uploading}
            onChange={(e) => handleFileUpload(e.target.files?.[0])}
          />
          <button type="button" className="btn" disabled={uploading} onClick={handleLoadSampleSLA}>
            <FileText size={15} /> Load Sample Supplier SLA
          </button>
        </div>

        {uploadStatus && (
          <div className="pill ok" style={{ marginTop: 12, borderRadius: 8 }}>
            {uploadStatus}
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="card-title">
          <Search size={17} color="#a855f7" /> Test Hybrid RAG Pipeline Tool
        </h3>
        <form onSubmit={handleRagQuery} style={{ display: "flex", gap: 8 }}>
          <input
            className="text-input"
            style={{ flex: 1 }}
            value={ragQuery}
            onChange={(e) => setRagQuery(e.target.value)}
            placeholder="Ask a question about uploaded policies..."
          />
          <button type="submit" className="btn btn-primary" disabled={querying}>
            {querying ? "Searching..." : "Ask RAG"}
          </button>
        </form>

        {ragResponse && (
          <div style={{ marginTop: 14 }}>
            <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
              {ragResponse.domain && <span className="pill accent">{ragResponse.domain}</span>}
              {ragResponse.tool_used && <span className="pill purple">{ragResponse.tool_used}</span>}
            </div>
            <div className="msg-bubble" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
              {ragResponse.response}
            </div>
            {ragResponse.sources?.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div className="muted" style={{ fontWeight: 600 }}>Citations:</div>
                {ragResponse.sources.map((s, idx) => (
                  <div key={idx} className="muted" style={{ marginTop: 4, fontSize: "0.78rem" }}>
                    <strong>{s.document}</strong> · rrf: {s.rrf_score} — {s.excerpt}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

