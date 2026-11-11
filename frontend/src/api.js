const API_BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

export const api = {
  getHealth: () => request("/health"),

  sendChat: (message, sessionId, requireHitl = true) =>
    request("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: sessionId || undefined,
        require_hitl: requireHitl,
      }),
    }),

  confirmAction: (sessionId, approved) =>
    request("/api/chat/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, approved }),
    }),

  getTools: (domain = "", q = "") => {
    const params = new URLSearchParams();
    if (domain) params.set("domain", domain);
    if (q) params.set("q", q);
    const qs = params.toString();
    return request(`/api/tools${qs ? `?${qs}` : ""}`);
  },

  retrieveTools: (query, domain = "", topK = 5) =>
    request("/api/tools/retrieve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        domain: domain || null,
        top_k: topK,
      }),
    }),

  uploadKBFile: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/kb/upload", {
      method: "POST",
      body: form,
    });
  },

  getSessionState: (sessionId) => request(`/api/sessions/${encodeURIComponent(sessionId)}`),

  getSessionTrace: (sessionId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/trace`),

  getObservability: () => request("/api/system/observability"),

  resetCircuitBreakers: () =>
    request("/api/system/circuit-breakers/reset", { method: "POST" }),
};

