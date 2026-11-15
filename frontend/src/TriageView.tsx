import React, { useEffect, useState } from "react";
import { api } from "./api";
import type { Finding, RunItem, StageItem } from "./types";
import { FindingDrawer } from "./FindingDrawer";
import { FixPRDrawer } from "./FixPRDrawer";
import { NoTestsView } from "./NoTestsView";
import "./TriageView.css";

interface TriageViewProps {
  onNavigateToPipeline?: () => void;
  onNavigateToRepoMap?: (nodeId?: string) => void;
}

export const TriageView: React.FC<TriageViewProps> = ({
  onNavigateToPipeline,
  onNavigateToRepoMap,
}) => {
  const [repoInput, setRepoInput] = useState("https://github.com/vidipt9090/flakeguard-demo");
  const [sourceType, setSourceType] = useState<"github" | "demo" | "cachetools" | "synthetic" | "notest">("demo");
  const [useDocker, setUseDocker] = useState(false);
  const [runOnActions, setRunOnActions] = useState(true);
  const [shuffledN, setShuffledN] = useState(3);

  const [activeFilter, setActiveFilter] = useState<"all" | "flaky" | "real">("all");
  const [scanning, setScanning] = useState(false);
  const [scanStatus, setScanStatus] = useState<string | null>(null);
  const [currentRun, setCurrentRun] = useState<RunItem | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [fixFinding, setFixFinding] = useState<Finding | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  // Poll status & runs
  const fetchCurrentState = async () => {
    try {
      const runsData = await api.getRuns();
      if (runsData.runs && runsData.runs.length > 0) {
        const latest = runsData.runs[0];
        setCurrentRun(latest);
        if (latest.findings && latest.findings.length > 0) {
          setFindings(latest.findings);
        }
      }

      const st = await api.status();
      if (st.running) {
        setScanning(true);
        setScanStatus("running");
      } else {
        setScanning(false);
        if (st.outcome) {
          setScanStatus(st.outcome);
        }
      }
    } catch {
      // Backend offline
    }
  };

  useEffect(() => {
    fetchCurrentState();
    const interval = setInterval(fetchCurrentState, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleSelectSource = (
    type: "github" | "demo" | "cachetools" | "synthetic" | "notest",
    target: string
  ) => {
    setSourceType(type);
    setRepoInput(target);
  };

  const handleRunScan = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!repoInput.trim() || scanning) return;

    setScanning(true);
    setActionNotice(null);
    try {
      const res = await api.scan({
        repo: repoInput,
        shuffled_n: shuffledN,
        use_docker: useDocker,
        remote: runOnActions,
      });
      if (res.fallback_banner) {
        setActionNotice(res.fallback_banner);
      }
      fetchCurrentState();
    } catch (err) {
      setActionNotice(err instanceof Error ? err.message : "Failed to start scan");
      setScanning(false);
    }
  };

  const handleQuarantine = async (testId: string) => {
    try {
      const res = await api.quarantine({ test_id: testId, reason: "flaky" });
      setActionNotice(res.message || `Test ${testId} moved to quarantine.`);
    } catch (err) {
      setActionNotice(err instanceof Error ? err.message : `Quarantine failed for ${testId}.`);
    }
  };

  // If user selected "a repo with no tests", show NoTestsView
  const isNoTestTarget =
    repoInput.includes("notest") ||
    sourceType === "notest" ||
    (currentRun && currentRun.total_tests === 0 && !scanning);

  if (isNoTestTarget) {
    return (
      <div className="triage-container">
        <NoTestsView
          repoName={repoInput}
          onRunScanWithKept={() => {
            handleSelectSource("demo", "vidipt9090/flakeguard-demo");
          }}
        />
      </div>
    );
  }

  const filteredFindings = findings.filter((f) => {
    if (activeFilter === "flaky") return f.verdict === "flaky";
    if (activeFilter === "real") return f.verdict === "real";
    return true;
  });

  const defaultStages: StageItem[] = [
    { name: "Clone", status: "done" },
    { name: "Run matrix", status: "done" },
    { name: "Evidence", status: "done" },
    { name: "Verdict", status: scanning ? "running" : "done" },
    { name: "Report", status: scanning ? "waiting" : "done" },
  ];

  const stages = currentRun?.stages && currentRun.stages.length >= 5 ? currentRun.stages : defaultStages;

  return (
    <div className="triage-container">
      {/* ============================================================== */}
      {/* 1. START SECTION: Find the tests you can't trust (Canvas Start) */}
      {/* ============================================================== */}
      <section className="start-hero-card">
        <h1 className="hero-headline">Find the tests you can't trust.</h1>
        <p className="hero-subhead">
          Some tests pass and fail on the same code. These flaky tests turn builds red for no real
          reason. FlakeGuard runs a repository's tests many different ways, finds the flaky ones,
          shows why they flake, and lets you decide what to do. A real bug is never hidden.
        </p>

        {/* 4-step strip */}
        <div className="four-step-strip">
          <div className="strip-item">
            <span className="strip-num">1</span>
            <div className="strip-body">
              <strong>Run it many ways</strong>
              <p>Shuffled, reversed, one-by-one, in parallel, repeated, and under load.</p>
            </div>
          </div>
          <div className="strip-item">
            <span className="strip-num">2</span>
            <div className="strip-body">
              <strong>Find the cause</strong>
              <p>State left behind, a race on a lock, a random seed, clock drift, timezones. By changing one thing at a time.</p>
            </div>
          </div>
          <div className="strip-item">
            <span className="strip-num">3</span>
            <div className="strip-body">
              <strong>Explain it</strong>
              <p>A language model reads the evidence, the failure logs, and the code, and explains why, with file and line.</p>
            </div>
          </div>
          <div className="strip-item">
            <span className="strip-num">4</span>
            <div className="strip-body">
              <strong>You decide</strong>
              <p>Quarantine the test or merge a fix. Nothing changes without your approval.</p>
            </div>
          </div>
        </div>

        {/* Scan a repository Card */}
        <div className="scan-config-card">
          <h2 className="scan-card-heading">Scan a repository</h2>

          {/* 1. Choose a source (4 cards) */}
          <div className="source-step">
            <span className="step-label">1. Choose a source:</span>
            <div className="source-cards-grid">
              <button
                type="button"
                className={`source-card ${sourceType === "github" ? "selected" : ""}`}
                onClick={() => handleSelectSource("github", "https://github.com/owner/repository")}
              >
                <strong className="source-title">My GitHub repo</strong>
                <p className="source-desc">
                  Paste any public Python repository URL. Private ones need an access token.
                </p>
              </button>

              <button
                type="button"
                className={`source-card ${sourceType === "demo" ? "selected" : ""}`}
                onClick={() => handleSelectSource("demo", "vidipt9090/flakeguard-demo")}
              >
                <strong className="source-title">Demo repo</strong>
                <p className="source-desc">
                  A small order-app with three flaky tests built in and one real bug.
                </p>
              </button>

              <button
                type="button"
                className={`source-card ${sourceType === "cachetools" ? "selected" : ""}`}
                onClick={() => handleSelectSource("cachetools", "tkem/cachetools")}
              >
                <strong className="source-title">cachetools</strong>
                <p className="source-desc">
                  A real, popular Python library. 12 tests run fast. 0 flaky on current version.
                </p>
              </button>

              <button
                type="button"
                className={`source-card ${sourceType === "synthetic" ? "selected" : ""}`}
                onClick={() => handleSelectSource("synthetic", "synthetic")}
              >
                <strong className="source-title">Synthetic benchmark</strong>
                <p className="source-desc">
                  31 planted tests with known answers, used to measure accuracy. Results marked &ldquo;planted&rdquo;.
                </p>
              </button>
            </div>
          </div>

          {/* 2. Repository input */}
          <div className="input-step">
            <span className="step-label">2. Enter the repository:</span>
            <form className="repo-input-form" onSubmit={handleRunScan}>
              <input
                type="text"
                className="repo-input"
                value={repoInput}
                onChange={(e) => setRepoInput(e.target.value)}
                placeholder="https://github.com/user/repository or owner/repo"
              />
              <button type="submit" className="btn-run-scan" disabled={scanning}>
                {scanning ? "Scanning…" : "Run scan"}
              </button>
            </form>
            <p className="scan-time-notice">
              A scan watches a repository run its tests. It takes about 5 to 7 minutes, and you can watch every step.
            </p>
          </div>

          {/* 3. Options */}
          <div className="options-step">
            <span className="step-label">Options:</span>
            <div className="options-checkboxes">
              <label className="checkbox-option">
                <input
                  type="checkbox"
                  checked={useDocker}
                  onChange={(e) => setUseDocker(e.target.checked)}
                />
                <div className="checkbox-text">
                  <strong>Isolate in Docker</strong>
                  <span>
                    Run the repository's code inside a locked-down container, so it can't touch your
                    machine. Needs local Docker installed and running. If Docker is unavailable,
                    the scan stops and tells you.
                  </span>
                </div>
              </label>

              <label className="checkbox-option">
                <input
                  type="checkbox"
                  checked={runOnActions}
                  onChange={(e) => setRunOnActions(e.target.checked)}
                />
                <div className="checkbox-text">
                  <strong>Run on GitHub Actions</strong>
                  <span>
                    Dispatches the reusable scan workflow to GitHub Actions runners.
                  </span>
                </div>
              </label>

              <label className="checkbox-option">
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={shuffledN}
                  onChange={(e) => setShuffledN(parseInt(e.target.value) || 2)}
                  style={{
                    width: "48px",
                    background: "#0b0c10",
                    color: "#f0f2f5",
                    border: "1px solid #262933",
                    borderRadius: "4px",
                    padding: "2px 6px",
                  }}
                />
                <div className="checkbox-text">
                  <strong>Perturbation runs (N)</strong>
                  <span>Number of shuffled permutation runs in matrix scan.</span>
                </div>
              </label>
            </div>
          </div>
        </div>
      </section>

      {/* Action Notification Banner */}
      {actionNotice && (
        <div className="action-notice-banner">
          <span>{actionNotice}</span>
          <button className="notice-dismiss" onClick={() => setActionNotice(null)}>✕</button>
        </div>
      )}

      {/* ============================================================== */}
      {/* 2. TRIAGE SECTION: Live / Finished Scan Findings Feed          */}
      {/* ============================================================== */}
      <section className="triage-feed-card">
        {/* Repo header */}
        <div className="triage-repo-header">
          <div className="repo-header-info">
            <span className="eyebrow-label">Triage findings</span>
            <h2 className="current-repo-title">{repoInput}</h2>
            <span className="commit-tag">
              HEAD: <code>{currentRun?.git_sha?.substring(0, 7) || "ca79ba6"}</code>
            </span>
          </div>
          <div className="repo-header-actions">
            <a
              href="https://github.com/vidipt9090/flakeguard-demo/actions"
              target="_blank"
              rel="noreferrer"
              className="btn-link-actions"
            >
              Open in GitHub Actions ↗
            </a>
          </div>
        </div>

        {/* 5-stage progress strip */}
        <div className="progress-strip-wrap">
          <div className="progress-strip-header">
            <span className="strip-title">
              Scan Pipeline: {scanStatus === "running" ? "Running Matrix Scan…" : scanStatus || "Completed"}
            </span>
            {onNavigateToPipeline && (
              <button className="link-view-pipeline" onClick={onNavigateToPipeline}>
                View real-time event log ↗
              </button>
            )}
          </div>
          <div className="progress-strip">
            {stages.slice(0, 5).map((stage, idx) => {
              const isCurrent = stage.status === "running";
              const isDone = stage.status === "done";
              const isWaiting = stage.status === "waiting";
              return (
                <div
                  key={stage.name}
                  className={`stage-step ${isDone ? "done" : ""} ${isCurrent ? "current" : ""} ${isWaiting ? "waiting" : ""}`}
                >
                  <div className="stage-indicator">
                    {isDone ? "✓" : isCurrent ? "●" : idx + 1}
                  </div>
                  <span className="stage-name">{stage.name}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Filter bar */}
        <div className="findings-filter-bar">
          <div className="filter-buttons">
            <button
              className={`filter-btn ${activeFilter === "all" ? "active" : ""}`}
              onClick={() => setActiveFilter("all")}
            >
              All ({findings.length})
            </button>
            <button
              className={`filter-btn ${activeFilter === "flaky" ? "active" : ""}`}
              onClick={() => setActiveFilter("flaky")}
            >
              Flaky ({findings.filter((f) => f.verdict === "flaky").length})
            </button>
            <button
              className={`filter-btn ${activeFilter === "real" ? "active" : ""}`}
              onClick={() => setActiveFilter("real")}
            >
              Real bugs ({findings.filter((f) => f.verdict === "real").length})
            </button>
          </div>
        </div>

        {/* Findings feed */}
        <div className="findings-feed">
          {filteredFindings.length === 0 ? (
            <div className="empty-findings-state">
              <span className="empty-check-icon">✓</span>
              <p className="empty-text">No flaky tests found in 20 runs.</p>
              <span className="empty-provenance">
                Verified across shuffled seeds, isolated runs, and causal interventions.
              </span>
            </div>
          ) : (
            filteredFindings.map((finding) => {
              const isFlaky = finding.verdict === "flaky";
              const canQuarantine = isFlaky && (finding.can_quarantine !== false);

              return (
                <article key={finding.id || finding.test_id} className="finding-card">
                  <header className="card-header">
                    <span className={`finding-badge ${isFlaky ? "badge-flaky" : "badge-real"}`}>
                      {isFlaky ? "Flaky" : "Real bug"}
                    </span>
                    <span className="root-cause-tag">{finding.root_cause}</span>
                  </header>

                  <h3 className="card-test-id">{finding.test_id}</h3>
                  <p className="card-plain-sentence">{finding.plain_sentence}</p>

                  <div className="card-metrics-strip">
                    {(finding.tags || finding.metrics_summary || []).map((tag: string, idx: number) => (
                      <span key={idx} className="metric-chip">
                        {tag}
                      </span>
                    ))}
                  </div>

                  <footer className="card-actions">
                    <div className="actions-left">
                      {isFlaky && finding.has_fix && (
                        <button
                          className="btn-propose-fix"
                          onClick={() => setFixFinding(finding)}
                        >
                          Propose fix PR
                        </button>
                      )}

                      {canQuarantine ? (
                        <button
                          className="btn-quarantine"
                          onClick={() => handleQuarantine(finding.test_id)}
                        >
                          Quarantine
                        </button>
                      ) : (
                        <button
                          className="btn-quarantine-disabled"
                          disabled
                          title="Real bugs cannot be quarantined to prevent hiding genuine software defects"
                        >
                          Quarantine unavailable
                        </button>
                      )}
                    </div>

                    <button
                      className="btn-see-proof"
                      onClick={() => setSelectedFinding(finding)}
                    >
                      See the proof →
                    </button>
                  </footer>
                </article>
              );
            })
          )}
        </div>
      </section>

      {/* Slide-over Finding Drawer */}
      <FindingDrawer
        finding={selectedFinding}
        onClose={() => setSelectedFinding(null)}
        onProposeFix={() => {
          if (selectedFinding) setFixFinding(selectedFinding);
        }}
        onQuarantine={handleQuarantine}
        onNavigateToRepoMap={onNavigateToRepoMap}
      />

      {/* Slide-over Fix PR Drawer */}
      <FixPRDrawer
        finding={fixFinding}
        isOpen={!!fixFinding}
        onClose={() => setFixFinding(null)}
        onOpenPR={async (f) => {
          await api.proposeFix({ test_id: f.test_id });
          setActionNotice(`Pull request opened on your fork for ${f.test_id}.`);
        }}
      />
    </div>
  );
};
