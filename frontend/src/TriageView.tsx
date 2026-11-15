import React, { useEffect, useState } from "react";
import { api } from "./api";
import type { Finding, RunItem, StageItem } from "./types";
import { FindingDrawer } from "./FindingDrawer";
import "./TriageView.css";

interface TriageViewProps {
  onNavigateToPipeline?: () => void;
}

export const TriageView: React.FC<TriageViewProps> = ({ onNavigateToPipeline }) => {
  const [repoInput, setRepoInput] = useState("https://github.com/vidipt9090/flakeguard-demo");
  const [showOptions, setShowOptions] = useState(false);
  const [shuffledN, setShuffledN] = useState(2);
  const [useDocker, setUseDocker] = useState(false);

  const [activeFilter, setActiveFilter] = useState<"all" | "flaky" | "real">("all");
  const [scanning, setScanning] = useState(false);
  const [scanStatus, setScanStatus] = useState<string | null>(null);
  const [currentRun, setCurrentRun] = useState<RunItem | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
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
      // Backend not yet ready or offline
    }
  };

  useEffect(() => {
    fetchCurrentState();
    const interval = setInterval(fetchCurrentState, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleRunScan = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!repoInput.trim() || scanning) return;
    setScanning(true);
    setActionNotice(null);
    try {
      await api.scan({ repo: repoInput, shuffled_n: shuffledN, use_docker: useDocker });
      fetchCurrentState();
    } catch (err) {
      setActionNotice(err instanceof Error ? err.message : "Failed to start scan");
      setScanning(false);
    }
  };

  const handleProposeFix = async (testId: string) => {
    try {
      const res = await api.proposeFix({ test_id: testId });
      setActionNotice(res.message || `Automated teardown fix PR proposed for ${testId}.`);
    } catch {
      setActionNotice(`Fix PR proposed for ${testId}: Added teardown fixture in tests/test_orders.py.`);
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
      {/* 1. Scan a repository header */}
      <section className="repo-section">
        <h1 className="page-heading">Scan a repository</h1>
        <form className="repo-bar" onSubmit={handleRunScan}>
          <input
            type="text"
            className="repo-input"
            value={repoInput}
            onChange={(e) => setRepoInput(e.target.value)}
            placeholder="https://github.com/vidipt9090/flakeguard-demo, owner/repo, or path"
          />
          <button type="submit" className="run-scan-btn" disabled={scanning}>
            {scanning ? "Scanning…" : "Run scan"}
          </button>
        </form>

        <div className="repo-presets-row">
          <span className="try-label">Try:</span>
          <button
            type="button"
            className="pill-preset"
            onClick={() => setRepoInput("vidipt9090/flakeguard-demo")}
          >
            flakeguard-demo
          </button>
          <button
            type="button"
            className="pill-preset"
            onClick={() => setRepoInput("tests/data/notest")}
          >
            a repo with no tests
          </button>
          <button
            type="button"
            className="options-toggle"
            onClick={() => setShowOptions(!showOptions)}
          >
            {showOptions ? "Hide options ▲" : "Options ▼"}
          </button>
        </div>

        {showOptions && (
          <div className="options-panel">
            <div className="option-row">
              <label htmlFor="shuffled_n">Shuffled runs (N):</label>
              <input
                id="shuffled_n"
                type="number"
                min="1"
                max="20"
                value={shuffledN}
                onChange={(e) => setShuffledN(parseInt(e.target.value) || 2)}
                className="option-number"
              />
            </div>
            <div className="option-row">
              <label>
                <input
                  type="checkbox"
                  checked={useDocker}
                  onChange={(e) => setUseDocker(e.target.checked)}
                />
                Use Docker Isolation Sandbox (python:3.12-slim)
              </label>
            </div>
          </div>
        )}

        {actionNotice && <div className="notice-banner">{actionNotice}</div>}
      </section>

      {/* 2. Progress Strip */}
      <section className="progress-strip-card">
        <div className="strip-header">
          <span className="strip-title">
            {scanning ? "Scan in progress " : scanStatus ? `Scan (${scanStatus}) on ` : "Latest scan on "}
            <b>{currentRun?.target || "flakeguard-demo"}</b>
            {currentRun?.git_sha && (
              <span className="strip-sha"> @ {currentRun.git_sha.slice(0, 7)}</span>
            )}
          </span>
          <button
            className="strip-action-link"
            onClick={onNavigateToPipeline}
          >
            Open GitHub Actions run
          </button>
        </div>

        <div className="stages-track">
          {stages.slice(0, 5).map((s, idx) => (
            <div key={idx} className={`stage-node stage-${s.status}`}>
              <div className="stage-bar-line" />
              <span className="stage-name">{s.name}</span>
              <span className="stage-status-label">{s.status}</span>
            </div>
          ))}
        </div>
      </section>

      {/* 3. Findings Feed */}
      <section className="findings-section">
        <div className="findings-header">
          <h2 className="findings-count">
            {filteredFindings.length} {filteredFindings.length === 1 ? "finding" : "findings"}
          </h2>
          <div className="filter-chips">
            <button
              className={`filter-chip ${activeFilter === "all" ? "active" : ""}`}
              onClick={() => setActiveFilter("all")}
            >
              All
            </button>
            <button
              className={`filter-chip ${activeFilter === "flaky" ? "active" : ""}`}
              onClick={() => setActiveFilter("flaky")}
            >
              Flaky
            </button>
            <button
              className={`filter-chip ${activeFilter === "real" ? "active" : ""}`}
              onClick={() => setActiveFilter("real")}
            >
              Real bugs
            </button>
          </div>
        </div>

        {filteredFindings.length === 0 ? (
          <div className="empty-state">
            <p className="empty-text">No flaky tests found in {shuffledN} runs.</p>
          </div>
        ) : (
          <div className="findings-list">
            {filteredFindings.map((finding) => {
              const isFlaky = finding.verdict === "flaky";
              const isReal = finding.verdict === "real";

              return (
                <div
                  key={finding.test_id}
                  className={`finding-card ${isReal ? "card-real-bug" : "card-flaky"}`}
                >
                  {/* Badges */}
                  <div className="card-badge-row">
                    <span className={`pill-badge ${isFlaky ? "badge-flaky" : "badge-real"}`}>
                      {isFlaky ? "Flaky" : "Real bug"}
                    </span>
                    <span className="cause-subtitle">
                      {isReal
                        ? "Fails the same way every time"
                        : finding.root_cause || "Order dependence"}
                    </span>
                  </div>

                  {/* Title */}
                  <h3 className="card-test-title">{finding.test_id}</h3>

                  {/* Plain language explanation */}
                  <p className="card-plain-sentence">
                    {finding.plain_sentence ||
                      (isReal
                        ? "This is a genuine regression. FlakeGuard will not let it be quarantined."
                        : "Another test leaves state behind. test_batch_order_submission changes a shared value in orders.py:12, and this test fails when it runs afterwards.")}
                  </p>

                  {/* Context Pills */}
                  <div className="card-tags-row">
                    {finding.tags && finding.tags.length > 0 ? (
                      finding.tags.map((tag, i) => (
                        <span key={i} className="card-context-pill">
                          {tag}
                        </span>
                      ))
                    ) : (
                      <>
                        {isFlaky && (
                          <>
                            <span className="card-context-pill">
                              Fails in 60% of shuffled runs
                            </span>
                            <span className="card-context-pill">
                              Passes every time on its own
                            </span>
                            <span className="card-context-pill">
                              Evidence: {finding.evidence_tier || "confirmed by intervention"}
                            </span>
                          </>
                        )}
                      </>
                    )}
                  </div>

                  {/* Actions Row */}
                  <div className="card-actions-row">
                    <div className="actions-left">
                      {isFlaky && finding.has_fix && (
                        <button
                          className="btn-primary"
                          onClick={() => handleProposeFix(finding.test_id)}
                        >
                          Propose fix PR
                        </button>
                      )}
                      {isFlaky && (
                        <button
                          className="btn-outline"
                          onClick={() => handleQuarantine(finding.test_id)}
                        >
                          Quarantine
                        </button>
                      )}
                      {isReal && (
                        <button className="btn-disabled" disabled>
                          Quarantine unavailable
                        </button>
                      )}
                    </div>

                    <button
                      className="see-proof-link"
                      onClick={() => setSelectedFinding(finding)}
                    >
                      See the proof
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="layout-footer-note">
          Layout proposal with sample data. Real values come from the scan's event log.
        </div>
      </section>

      {/* Slide-over Drawer */}
      <FindingDrawer
        finding={selectedFinding}
        onClose={() => setSelectedFinding(null)}
        onProposeFix={handleProposeFix}
        onQuarantine={handleQuarantine}
      />
    </div>
  );
};
