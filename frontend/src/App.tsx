import { useEffect, useState } from "react";
import { TriageView } from "./TriageView";
import { RepoMapView } from "./RepoMapView";
import { PipelineView } from "./PipelineView";
import { ResultsView } from "./ResultsView";
import "./App.css";

type Tab = "triage" | "repomap" | "pipeline" | "results";

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>(() => {
    try {
      const hash = window.location.hash.replace("#", "") as Tab;
      if (["triage", "repomap", "pipeline", "results"].includes(hash)) return hash;
    } catch {
      // ignore
    }
    return "triage";
  });
  const [highlightRepoMapNode, setHighlightRepoMapNode] = useState<string | null>(null);

  useEffect(() => {
    window.location.hash = activeTab;
  }, [activeTab]);

  const handleNavigateToRepoMap = (nodeId?: string) => {
    if (nodeId) {
      setHighlightRepoMapNode(nodeId);
    }
    setActiveTab("repomap");
  };

  return (
    <div className="app-shell">
      {/* Top Navigation Bar matching proposal header */}
      <header className="app-topbar">
        <div className="topbar-inner">
          <div className="brand-group">
            <span className="brand-name">FlakeGuard</span>
            <span className="brand-tagline">flaky-test triage for pull requests</span>
          </div>

          <nav className="tab-nav">
            <button
              className={`nav-tab-btn ${activeTab === "triage" ? "active" : ""}`}
              onClick={() => setActiveTab("triage")}
            >
              Triage
            </button>
            <button
              className={`nav-tab-btn ${activeTab === "repomap" ? "active" : ""}`}
              onClick={() => setActiveTab("repomap")}
            >
              Repo map
            </button>
            <button
              className={`nav-tab-btn ${activeTab === "pipeline" ? "active" : ""}`}
              onClick={() => setActiveTab("pipeline")}
            >
              Pipeline
            </button>
            <button
              className={`nav-tab-btn ${activeTab === "results" ? "active" : ""}`}
              onClick={() => setActiveTab("results")}
            >
              Results
            </button>
          </nav>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="app-main">
        {activeTab === "triage" && (
          <TriageView
            onNavigateToPipeline={() => setActiveTab("pipeline")}
            onNavigateToRepoMap={handleNavigateToRepoMap}
          />
        )}
        {activeTab === "repomap" && (
          <RepoMapView initialHighlightNodeId={highlightRepoMapNode} />
        )}
        {activeTab === "pipeline" && <PipelineView />}
        {activeTab === "results" && <ResultsView />}
      </main>
    </div>
  );
}
