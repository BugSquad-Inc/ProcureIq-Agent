import React, { useEffect, useState } from "react";
import {
  Home,
  MessageSquare,
  Wrench,
  BookOpen,
  Activity,
  Moon,
  Sun,
  Settings,
  Wifi,
} from "lucide-react";
import { api } from "./api";
import HomeDashboard from "./components/Home/HomeDashboard";
import ChatPanel from "./components/ChatInterface/ChatPanel";
import ToolCatalog from "./components/ToolExplorer/ToolCatalog";
import ToolExplorer from "./components/ToolExplorer/ToolExplorer";
import KnowledgeBasePanel from "./components/KnowledgeBase/KnowledgeBasePanel";
import ObservabilityPanel from "./components/Observability/ObservabilityPanel";
import SettingsPanel from "./components/Settings/SettingsPanel";

function generateSessionId() {
  return `demo-${Math.random().toString(36).slice(2, 8)}`;
}

const RAIL_ITEMS = [
  { id: "home", label: "HOME", icon: Home, matches: ["home"] },
  { id: "chat", label: "AGENT", icon: MessageSquare, matches: ["chat"] },
  { id: "tool_catalog", label: "TOOLS", icon: Wrench, matches: ["tool_catalog", "tools"] },
  { id: "kb", label: "DOCS", icon: BookOpen, matches: ["kb"] },
  { id: "obs", label: "TRACE", icon: Activity, matches: ["obs"] },
];

export default function App() {
  const [activeView, setActiveView] = useState("home");
  const [theme, setTheme] = useState("light");
  const [pendingPrompt, setPendingPrompt] = useState("");
  const [sessionId, setSessionId] = useState(() => generateSessionId());
  const [health, setHealth] = useState(null);

  const loadHealth = async () => {
    try {
      const h = await api.getHealth();
      setHealth(h);
    } catch {
      setHealth({ status: "disconnected", database: "disconnected", active_tools: 0 });
    }
  };

  useEffect(() => {
    loadHealth();
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const isOnline = health?.status === "ok";

  return (
    <div className="workspace-shell">
      {/* Far-Left Dark Icon Rail */}
      <aside className="icon-rail">
        <div className="rail-top">
          <button
            type="button"
            className="rail-logo-btn"
            onClick={() => setActiveView("home")}
            title="ProcureIQ — Dynamic Tool RAG"
            aria-label="ProcureIQ Home"
          >
            <svg viewBox="0 0 40 40" width="24" height="24" fill="none" aria-hidden="true">
              <defs>
                <linearGradient id="pqCore" x1="6" y1="6" x2="34" y2="34" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="#ffffff" />
                  <stop offset="100%" stopColor="#d1fae5" />
                </linearGradient>
              </defs>
              <circle cx="18.5" cy="18.5" r="9.5" stroke="url(#pqCore)" strokeWidth="3.2" />
              <path d="M24 24L32.5 32.5" stroke="#ffffff" strokeWidth="3.2" strokeLinecap="round" />
              <circle cx="18.5" cy="18.5" r="3" fill="#ffffff" />
              <circle cx="31" cy="10" r="2.6" fill="#a7f3d0" />
              <path d="M25.5 13.2L29 11" stroke="#a7f3d0" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
          {RAIL_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = item.matches.includes(activeView);
            return (
              <button
                key={item.id}
                type="button"
                className={`rail-item ${isActive ? "active" : ""}`}
                onClick={() => setActiveView(item.id)}
                title={item.label}
              >
                <div className="rail-icon-wrap">
                  <Icon size={18} />
                </div>
                <span className="rail-label">{item.label}</span>
              </button>
            );
          })}
        </div>

        <div className="rail-bottom">
          <button
            type="button"
            className="rail-item"
            onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
            title="Toggle Light/Dark Theme"
          >
            <div className="rail-icon-wrap">
              {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
            </div>
            <span className="rail-label">THEME</span>
          </button>

          <button
            type="button"
            className={`rail-item ${activeView === "settings" ? "active" : ""}`}
            onClick={() => setActiveView("settings")}
            title="Settings & System Status"
          >
            <div className="rail-icon-wrap">
              <Settings size={18} />
            </div>
            <span className="rail-label">SETTINGS</span>
          </button>
        </div>
      </aside>

      {/* Main Content Canvas */}
      <main className="main-surface">
        <div className="surface-topbar">
          <span className={`online-pill ${isOnline ? "" : "offline"}`}>
            <Wifi size={13} />
            {isOnline ? "Online" : "Offline"}
          </span>
        </div>

        <div className="surface-body">
          {activeView === "home" && (
            <HomeDashboard
              sessionId={sessionId}
              health={health}
              onNavigate={setActiveView}
            />
          )}
          {activeView === "chat" && (
            <ChatPanel
              sessionId={sessionId}
              onTurnComplete={loadHealth}
              initialPrompt={pendingPrompt}
              onPromptConsumed={() => setPendingPrompt("")}
            />
          )}
          {activeView === "tool_catalog" && (
            <ToolCatalog
              onTryPrompt={(prompt) => {
                setPendingPrompt(prompt);
                setActiveView("chat");
              }}
              onOpenRagExplorer={() => setActiveView("tools")}
            />
          )}
          {activeView === "tools" && (
            <ToolExplorer onBackToCatalog={() => setActiveView("tool_catalog")} />
          )}
          {activeView === "kb" && (
            <KnowledgeBasePanel sessionId={sessionId} onUploaded={loadHealth} />
          )}
          {activeView === "obs" && <ObservabilityPanel sessionId={sessionId} />}
          {activeView === "settings" && (
            <SettingsPanel
              sessionId={sessionId}
              health={health}
              onNewSession={() => setSessionId(generateSessionId())}
              onRefreshHealth={loadHealth}
            />
          )}
        </div>
      </main>
    </div>
  );
}
