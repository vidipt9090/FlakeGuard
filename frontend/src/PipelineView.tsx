import React, { useEffect, useState } from "react";
import { api } from "./api";
import type { RunItem } from "./types";
import { getActionsUrl } from "./utils";
import "./PipelineView.css";

export const PipelineView: React.FC = () => {
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("run-1");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchRuns = async () => {
      try {
        const res = await api.getRuns();
        if (res.runs && res.runs.length > 0) {
          const mappedRuns = res.runs.map((r: RunItem) => ({
            ...r,
            github_url: getActionsUrl(r.target || (r as any).repo),
          }));
          setRuns(mappedRuns);
          if (mappedRuns[0]) {
            setSelectedRunId(mappedRuns[0].id || mappedRuns[0].run_id || "run-1");
          }
        }
      } catch {
        // Fallback default runs
      } finally {
        setLoading(false);
      }
    };
    fetchRuns();
  }, []);

  const fallbackRuns: RunItem[] = [
    {
      id: "run-1",
      trigger: "PR opened",
      status: "Running",
      target: "vidipt9090/FlakeGuard",
      git_sha: "ca79ba6",
      github_url: "https://github.com/vidipt9090/FlakeGuard/actions",
      stages: [
        { name: "Clone", status: "done", duration_s: 4 },
        { name: "Run matrix", status: "done", duration_s: 38 },
        { name: "Evidence", status: "done", duration_s: 12 },
        { name: "Verdict", status: "running", duration_s: 8 },
        { name: "PR comment", status: "waiting", duration_s: 3 },
      ],
      human_steps: [
        { step: "Bot comment posted on the pull request", completed: true },
        { step: "Waiting for a maintainer to approve quarantine", completed: true },
        { step: "Quarantine commit added to the pull request branch", completed: true },
      ],
      latest_events: [
        "[ingest:started] target: vidipt9090/flakeguard-demo",
        "[evidence:result] polluter identified at orders.py:12 for test_initial_order_state",
        "[llm:verdict] model returned schema-validated verdict: flaky (order_dep)",
      ],
    },
    {
      id: "run-2",
      trigger: "Manual scan",
      status: "Done",
      target: "cachetools",
      git_sha: "8b01d4e",
      github_url: "https://github.com/tkem/cachetools/actions",
      stages: [
        { name: "Clone", status: "done", duration_s: 3 },
        { name: "Run matrix", status: "done", duration_s: 14 },
        { name: "Evidence", status: "done", duration_s: 5 },
        { name: "Verdict", status: "done", duration_s: 6 },
        { name: "PR comment", status: "done", duration_s: 2 },
      ],
      human_steps: [
        { step: "No flaky tests detected (zero-failure clean scan)", completed: true },
      ],
      latest_events: [
        "[discover:complete] 12 tests discovered across 2 suites",
        "[run:complete] 0 failures observed across 10 permutations",
      ],
    },
    {
      id: "run-3",
      trigger: "PR #42 updated",
      status: "Could not build",
      target: "unbuildable-repo",
      git_sha: "91c77ab",
      stages: [
        { name: "Clone", status: "error" },
        { name: "Run matrix", status: "waiting" },
      ],
      human_steps: [],
      latest_events: ["[ingest:error] could not build: target directory missing or unbuildable"],
    },
  ];

  const activeRuns = runs.length > 0 ? runs : fallbackRuns;
  const currentRun = activeRuns.find((r) => r.id === selectedRunId || r.run_id === selectedRunId) || activeRuns[0];

  return (
    <div className="pipeline-container">
      <header className="pipeline-header">
        <h1 className="pipeline-title">Pipeline</h1>
        <p className="pipeline-subtitle">
          What happened in GitHub Actions for each pull request or scan. This page only reads the run; the work itself happens in your workflow.
        </p>
      </header>

      {loading ? (
        <div className="pipeline-loading">Loading pipeline runs…</div>
      ) : (
        <div className="pipeline-layout">
          {/* Left Column: Recent Runs */}
          <aside className="recent-runs-column">
            <h2 className="recent-runs-heading">RECENT RUNS</h2>
            <div className="runs-list">
              {activeRuns.map((r) => {
                const isSelected = (r.id || r.run_id) === (currentRun?.id || currentRun?.run_id);
                const statusClass =
                  r.status === "Running"
                    ? "chip-running"
                    : r.status === "Done"
                    ? "chip-done"
                    : "chip-error";

                return (
                  <div
                    key={r.id || r.run_id}
                    className={`run-card ${isSelected ? "selected" : ""}`}
                    onClick={() => setSelectedRunId(r.id || r.run_id || "")}
                  >
                    <div className="run-card-top">
                      <span className="run-trigger">{r.trigger}</span>
                      <span className={`status-chip ${statusClass}`}>{r.status}</span>
                    </div>
                    <div className="run-card-sub">
                      {r.target} @ {r.git_sha ? r.git_sha.slice(0, 7) : "HEAD"}
                    </div>
                  </div>
                );
              })}
            </div>
          </aside>

          {/* Right Column: Run Details */}
          <main className="run-detail-column">
            {currentRun && (
              <>
                {/* 1. Stage Durations Card */}
                <div className="detail-card">
                  <div className="detail-card-header">
                    <div className="run-meta-wrap">
                      <h2 className="detail-run-name">
                        Run on {currentRun.target} @ {currentRun.git_sha ? currentRun.git_sha.slice(0, 7) : "HEAD"}
                      </h2>
                      {/* Sandbox Badge */}
                      <div className="sandbox-pill">
                        <span className="sandbox-label">Sandbox:</span>
                        <span className="sandbox-value">
                          {currentRun.target?.includes("docker")
                            ? "Docker container (python:3.12-slim)"
                            : "GitHub Actions runner (ubuntu-latest)"}
                        </span>
                      </div>
                    </div>
                    <a
                      href={getActionsUrl(currentRun.target || currentRun.github_url)}
                      target="_blank"
                      rel="noreferrer"
                      className="github-actions-link"
                    >
                      Open in GitHub Actions ↗
                    </a>
                  </div>

                  {/* Stage duration bars */}
                  <div className="stage-bars-list">
                    {(currentRun.stages || fallbackRuns[0].stages || []).map((stage, idx) => {
                      const isError = stage.status === "error";
                      const isWaiting = stage.status === "waiting";
                      const isRunning = stage.status === "running";
                      const durationStr = stage.duration_s ? `${stage.duration_s} s` : stage.duration || (isWaiting ? "â€”" : "3 s");

                      return (
                        <div key={idx} className="stage-bar-item">
                          <div className="stage-bar-header">
                            <span className="stage-bar-name">{stage.name}</span>
                            <span className="stage-bar-duration">{durationStr}</span>
                          </div>
                          <div className="stage-bar-track">
                            <div
                              className={`stage-bar-fill ${
                                isError
                                  ? "fill-error"
                                  : isWaiting
                                  ? "fill-waiting"
                                  : isRunning
                                  ? "fill-running"
                                  : "fill-done"
                              }`}
                              style={{ width: isWaiting ? "0%" : isRunning ? "65%" : "100%" }}
                            ></div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* 2. Where it ran column / grid */}
                <div className="detail-card">
                  <h3 className="section-title">WHERE IT RAN</h3>
                  <div className="where-grid">
                    <div className="where-cell">
                      <span className="where-stage-name">Matrix scan</span>
                      <strong className="where-runner">Actions runner</strong>
                      <span className="where-detail">ubuntu-latest (Python 3.12)</span>
                    </div>
                    <div className="where-cell">
                      <span className="where-stage-name">Evidence & bisection</span>
                      <strong className="where-runner">Actions runner</strong>
                      <span className="where-detail">ddmin delta debugging</span>
                    </div>
                    <div className="where-cell">
                      <span className="where-stage-name">LLM verdict</span>
                      <strong className="where-runner">Gemini 1.5 Flash</strong>
                      <span className="where-detail">Evidence-conditioned prompt v4</span>
                    </div>
                  </div>
                </div>

                {/* 3. Human Steps Checklist */}
                <div className="detail-card">
                  <h3 className="section-title">HUMAN STEPS</h3>
                  <div className="checklist-items">
                    {(currentRun.human_steps || fallbackRuns[0].human_steps || []).map((step, idx) => (
                      <div key={idx} className="checklist-row">
                        <span className={`checklist-icon ${step.completed ? "completed" : "pending"}`}>
                          {step.completed ? "✓" : "○"}
                        </span>
                        <span className="checklist-text">{step.step}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* 4. Latest Event Log Lines */}
                <div className="detail-card">
                  <div className="log-card-header">
                    <h3 className="section-title">LATEST EVENT LOG</h3>
                    <span className="log-count">
                      {(currentRun.latest_events || []).length} events
                    </span>
                  </div>
                  <div className="log-terminal">
                    {(currentRun.latest_events || fallbackRuns[0].latest_events || []).map((ev, idx) => (
                      <div key={idx} className="terminal-line">
                        <span className="line-prefix">&gt;</span>
                        <span className="line-text">{ev}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </main>
        </div>
      )}
    </div>
  );
};
