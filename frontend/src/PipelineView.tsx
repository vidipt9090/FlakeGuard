import React, { useEffect, useState } from "react";
import { api } from "./api";
import type { RunItem } from "./types";
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
          setRuns(res.runs);
          if (!selectedRunId) {
            setSelectedRunId(res.runs[0].id || res.runs[0].run_id || "run-1");
          }
        }
      } catch {
        // Fallback default runs matching design specification
      } finally {
        setLoading(false);
      }
    };
    fetchRuns();
  }, [selectedRunId]);

  const fallbackRuns: RunItem[] = [
    {
      id: "run-1",
      trigger: "PR opened",
      status: "Running",
      target: "flakeguard-demo",
      git_sha: "3f2a9c1",
      github_url: "https://github.com/vidipt9090/flakeguard-demo/actions",
      stages: [
        { name: "Clone", status: "done", duration_s: 4 },
        { name: "Run matrix", status: "done", duration_s: 38 },
        { name: "Evidence", status: "done", duration_s: 12 },
        { name: "Verdict", status: "running" },
        { name: "PR comment", status: "waiting" },
      ],
      human_steps: [
        { step: "Bot comment posted on the pull request", completed: true },
        { step: "Waiting for a maintainer to approve quarantine", completed: false },
        { step: "Quarantine commit added to the pull request branch", completed: false },
      ],
      latest_events: [
        "evidence result polluter found for 1 test",
        "llm started asking for a verdict",
      ],
    },
    {
      id: "run-2",
      trigger: "Manual scan",
      status: "Done",
      target: "a forked repo",
      git_sha: "8b01d4e",
      github_url: "https://github.com/vidipt9090/flakeguard-demo/actions",
      stages: [
        { name: "Clone", status: "done", duration_s: 3 },
        { name: "Run matrix", status: "done", duration_s: 24 },
        { name: "Evidence", status: "done", duration_s: 10 },
        { name: "Verdict", status: "done", duration_s: 6 },
        { name: "PR comment", status: "done", duration_s: 2 },
      ],
      human_steps: [
        { step: "Bot comment posted on the pull request", completed: true },
        { step: "Waiting for a maintainer to approve quarantine", completed: true },
        { step: "Quarantine commit added to the pull request branch", completed: true },
      ],
      latest_events: ["scan completed successfully"],
    },
    {
      id: "run-3",
      trigger: "PR opened",
      status: "Could not build",
      target: "flakeguard-demo",
      git_sha: "91c77ab",
      stages: [
        { name: "Clone", status: "error" },
        { name: "Run matrix", status: "waiting" },
      ],
      human_steps: [],
      latest_events: ["could not build: dependency resolution failure"],
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
                    <h2 className="detail-run-name">
                      Run on {currentRun.target} @ {currentRun.git_sha ? currentRun.git_sha.slice(0, 7) : "HEAD"}
                    </h2>
                    <a
                      href={currentRun.github_url || "https://github.com/vidipt9090/flakeguard-demo/actions"}
                      target="_blank"
                      rel="noreferrer"
                      className="github-actions-link"
                    >
                      Open in GitHub Actions
                    </a>
                  </div>

                  <div className="stage-bars-list">
                    {(currentRun.stages || fallbackRuns[0].stages || []).map((stage, idx) => {
                      const isDone = stage.status === "done";
                      const isRunning = stage.status === "running";
                      const isWaiting = stage.status === "waiting";
                      const isError = stage.status === "error";

                      const durationText = stage.duration_s
                        ? `${stage.duration_s} s`
                        : isRunning
                        ? "running"
                        : isWaiting
                        ? "waiting"
                        : isError
                        ? "failed"
                        : "done";

                      return (
                        <div key={idx} className="stage-duration-row">
                          <span className="stage-row-label">{stage.name}</span>
                          <div className="stage-row-track">
                            <div
                              className={`stage-row-fill stage-fill-${stage.status}`}
                              style={{
                                width: isDone
                                  ? `${Math.min(100, Math.max(15, (stage.duration_s || 10) * 2.2))}%`
                                  : isRunning
                                  ? "35%"
                                  : isWaiting
                                  ? "0%"
                                  : "20%",
                              }}
                            />
                          </div>
                          <span className={`stage-duration-val ${isRunning ? "text-running" : ""}`}>
                            {durationText}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* 2. Human Steps Checklist Card */}
                <div className="detail-card">
                  <h3 className="card-subheading">HUMAN STEPS</h3>
                  <div className="checklist">
                    {(currentRun.human_steps || fallbackRuns[0].human_steps || []).map((step, idx) => (
                      <div key={idx} className="checklist-item">
                        <span className={`check-dot ${step.completed ? "dot-completed" : "dot-waiting"}`} />
                        <span className="step-text">{step.step}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* 3. Event Log (Latest) Card */}
                <div className="event-log-card">
                  <h3 className="event-log-title">EVENT LOG (LATEST)</h3>
                  <div className="event-log-console">
                    {(currentRun.latest_events || fallbackRuns[0].latest_events || []).map((ev, idx) => (
                      <div key={idx} className="console-line">
                        {ev}
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </main>
        </div>
      )}

      <div className="layout-footer-note">
        Layout proposal with sample data. Stages and times come from the event log and the GitHub API.
      </div>
    </div>
  );
};
