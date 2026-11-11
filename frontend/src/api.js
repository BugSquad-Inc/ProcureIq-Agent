const API_BASE = import.meta.env.VITE_API_URL || "";

const STORAGE_KEYS = {
  tenantId: "procureiq_tenant_id",
  role: "procureiq_user_role",
  token: "procureiq_jwt_token",
};

export function getAuthConfig() {
  return {
    tenantId: localStorage.getItem(STORAGE_KEYS.tenantId) || "default",
    role: localStorage.getItem(STORAGE_KEYS.role) || "finance_vp",
    token: localStorage.getItem(STORAGE_KEYS.token) || "",
  };
}

export function setAuthConfig({ tenantId, role, token }) {
  if (tenantId !== undefined) localStorage.setItem(STORAGE_KEYS.tenantId, tenantId || "default");
  if (role !== undefined) localStorage.setItem(STORAGE_KEYS.role, role || "finance_vp");
  if (token !== undefined) {
    if (token) localStorage.setItem(STORAGE_KEYS.token, token);
    else localStorage.removeItem(STORAGE_KEYS.token);
  }
}

async function request(path, options = {}) {
  const cfg = getAuthConfig();
  const headers = {
    "X-Tenant-ID": cfg.tenantId,
    "X-User-Role": cfg.role,
    ...(cfg.token ? { Authorization: `Bearer ${cfg.token}` } : {}),
    ...(options.headers || {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    if (typeof data.detail === "string") {
      message = data.detail;
    } else if (Array.isArray(data.detail)) {
      message = data.detail.map((e) => e?.msg || JSON.stringify(e)).join("; ");
    } else if (data.detail) {
      message = JSON.stringify(data.detail);
    }
    throw new Error(message);
  }
  return data;
}

export const api = {
  getHealth: () => request("/health"),

  sendChat: (message, sessionId, requireHitl = true, confirmAll = false) =>
    request("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: sessionId || undefined,
        require_hitl: requireHitl,
        confirm_all: confirmAll,
      }),
    }),

  confirmAction: (sessionId, approved, params = null) =>
    request("/api/chat/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        approved,
        ...(params ? { params } : {}),
      }),
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

  getKBDocuments: () => request("/api/kb/documents"),

  deleteKBDocument: (documentName) =>
    request(`/api/kb/documents/${encodeURIComponent(documentName)}`, { method: "DELETE" }),

  getSessionState: (sessionId) => request(`/api/sessions/${encodeURIComponent(sessionId)}`),

  getSessionTrace: (sessionId) => request(`/api/sessions/${encodeURIComponent(sessionId)}/trace`),

  getObservability: () => request("/api/system/observability"),

  resetCircuitBreakers: () =>
    request("/api/system/circuit-breakers/reset", { method: "POST" }),

  issueToken: (userId, tenantId, role) =>
    request("/api/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, tenant_id: tenantId, role }),
    }),

  getAuthMe: () => request("/api/auth/me"),
};

