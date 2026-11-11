import React, { useEffect, useState } from "react";
import { Search, Cpu, ArrowLeft } from "lucide-react";
import { api } from "../../api";

export default function ToolExplorer({ onBackToCatalog }) {
  const [query, setQuery] = useState("send an invoice for $50 to client@example.com");
  const [topK, setTopK] = useState(5);
  const [retrievalResult, setRetrievalResult] = useState(null);
  const [retrieving, setRetrieving] = useState(false);

  const [catalog, setCatalog] = useState({ total: 0, domains: {}, tools: [] });
  const [domainFilter, setDomainFilter] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [error, setError] = useState("");

  const loadCatalog = async (dom = domainFilter, q = searchFilter) => {
    try {
      const data = await api.getTools(dom, q);
      setCatalog(data);
    } catch (err) {
      setError(err.message);
    }
  };

  const runRetrieve = async (e) => {
    e?.preventDefault();
    if (!query.trim()) return;
    setRetrieving(true);
    setError("");
    try {
      const res = await api.retrieveTools(query.trim(), domainFilter, topK);
      setRetrievalResult(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setRetrieving(false);
    }
  };

  useEffect(() => {
    loadCatalog("", "");
    runRetrieve();
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 6 }}>
          <h3 className="card-title" style={{ margin: 0 }}>
            <Cpu size={17} color="#38bdf8" /> Semantic Tool RAG Explorer (Core Architecture Proof)
          </h3>
          {onBackToCatalog && (
            <button type="button" className="btn" onClick={onBackToCatalog}>
              <ArrowLeft size={14} /> Tool Catalog Cards
            </button>
          )}
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          Tests <span className="mono">POST /api/tools/retrieve</span>: embeds the query, runs
          pgvector cosine + OR-BM25 + RRF + reranking, and binds only top-K tools to the LLM.
        </p>

        <form onSubmit={runRetrieve} style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <input
            className="text-input"
            style={{ flex: 1, minWidth: 260 }}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Enter any natural-language user intent..."
          />
          <select
            className="select-input"
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
          >
            <option value={3}>Top-3</option>
            <option value={5}>Top-5</option>
            <option value={10}>Top-10</option>
          </select>
          <button type="submit" className="btn btn-primary" disabled={retrieving}>
            <Search size={15} /> {retrieving ? "Retrieving..." : "Retrieve Tools"}
          </button>
        </form>

        {error && <p style={{ color: "var(--red)", marginTop: 10 }}>{error}</p>}

        {retrievalResult && (
          <div style={{ marginTop: 14 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <span className="pill ok">
                Retrieved {retrievalResult.tools_retrieved} / {retrievalResult.total_active_tools} tools
              </span>
              <span className="pill accent">Latency: {retrievalResult.latency_ms} ms</span>
              <span className="pill">Provider: {retrievalResult.embedding_model}</span>
              <span className="pill">Reranker: {retrievalResult.reranker_mode}</span>
            </div>

            <table className="data-table">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Tool Name</th>
                  <th>Domain</th>
                  <th>Final Score</th>
                  <th>Cosine</th>
                  <th>BM25</th>
                  <th>Rerank</th>
                </tr>
              </thead>
              <tbody>
                {retrievalResult.tools.map((t, i) => (
                  <tr key={t.name}>
                    <td className="mono">#{i + 1}</td>
                    <td>
                      <div className="mono" style={{ fontWeight: 600 }}>{t.name}</div>
                      <div className="muted" style={{ fontSize: "0.78rem" }}>{t.description}</div>
                    </td>
                    <td><span className="pill accent">{t.domain}</span></td>
                    <td>
                      <span className="score-bar-track">
                        <span
                          className="score-bar-fill"
                          style={{ width: `${Math.min(100, Math.round(t.final_score * 100))}%` }}
                        />
                      </span>
                      <span className="mono">{t.final_score}</span>
                    </td>
                    <td className="mono">{t.cosine_sim}</td>
                    <td className="mono">{t.bm25_score}</td>
                    <td className="mono">{t.rerank_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
          <h3 className="card-title" style={{ margin: 0 }}>
            Tool Registry Catalog ({catalog.total} tools)
          </h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <select
              className="select-input"
              value={domainFilter}
              onChange={(e) => {
                setDomainFilter(e.target.value);
                loadCatalog(e.target.value, searchFilter);
              }}
            >
              <option value="">All Domains</option>
              {Object.entries(catalog.domains || {}).map(([dom, cnt]) => (
                <option key={dom} value={dom}>
                  {dom} ({cnt})
                </option>
              ))}
            </select>
            <input
              className="text-input"
              placeholder="Filter tools..."
              value={searchFilter}
              onChange={(e) => {
                setSearchFilter(e.target.value);
                loadCatalog(domainFilter, e.target.value);
              }}
            />
          </div>
        </div>

        <div style={{ maxHeight: 340, overflowY: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Domain</th>
                <th>Description</th>
                <th>Endpoint</th>
              </tr>
            </thead>
            <tbody>
              {catalog.tools.map((t) => (
                <tr key={t.id}>
                  <td className="mono">{t.name}</td>
                  <td><span className="pill">{t.domain}</span></td>
                  <td>{t.description}</td>
                  <td className="mono muted">{t.endpoint || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

