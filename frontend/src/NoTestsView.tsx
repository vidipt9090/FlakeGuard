import React, { useState } from "react";
import "./NoTestsView.css";

interface NoTestsViewProps {
  repoName?: string;
  onOpenPR?: () => Promise<void>;
  onRunScanWithKept?: () => void;
}

export const NoTestsView: React.FC<NoTestsViewProps> = ({
  repoName = "tests/data/notest/app.py",
  onOpenPR,
  onRunScanWithKept,
}) => {
  const [opening, setOpening] = useState(false);
  const [prOpened, setPrOpened] = useState(false);

  const handleOpenPR = async () => {
    setOpening(true);
    try {
      if (onOpenPR) await onOpenPR();
      setPrOpened(true);
    } catch {
      setPrOpened(true);
    } finally {
      setOpening(false);
    }
  };

  const riskySpots = [
    {
      spot: "scheduler.py:21",
      why: "Waits a fixed time with sleep",
      result: "Kept",
      status: "kept",
      detail: "Deterministic at HEAD across 10 shuffled runs",
    },
    {
      spot: "tokens.py:3",
      why: "Uses random numbers",
      result: "Kept",
      status: "kept",
      detail: "Deterministic when unseeded values isolated",
    },
    {
      spot: "reports.py:22",
      why: "Reads the current time",
      result: "Dropped: gave different results across runs",
      status: "dropped",
      detail: "Failed acceptance gate: output mutated with clock drift",
    },
    {
      spot: "cache.py:9",
      why: "Shared global state",
      result: "Checking",
      status: "checking",
      detail: "Evaluating mutant kill rate and independence",
    },
  ];

  return (
    <div className="notest-container">
      <div className="notest-card">
        <header className="notest-header">
          <span className="notest-badge">Target: {repoName}</span>
          <h1 className="notest-title">This repository has no tests</h1>
          <p className="notest-subhead">
            There is nothing to run yet, so FlakeGuard writes tests first. It looks for code that
            tends to behave differently from run to run, writes a small test for each spot, and
            keeps only the tests that pass and behave the same every time. Then it scans with them
            as usual.
          </p>
        </header>

        {/* 4-step strip */}
        <div className="notest-step-strip">
          <div className="notest-step done">
            <span className="step-num">1</span>
            <div className="step-text">
              <strong>Find risky code</strong>
              <span>4 spots found</span>
            </div>
          </div>
          <div className="notest-step done">
            <span className="step-num">2</span>
            <div className="step-text">
              <strong>Write tests</strong>
              <span>4 written</span>
            </div>
          </div>
          <div className="notest-step active">
            <span className="step-num">3</span>
            <div className="step-text">
              <strong>Check tests</strong>
              <span>2 of 4 kept</span>
            </div>
          </div>
          <div className="notest-step">
            <span className="step-num">4</span>
            <div className="step-text">
              <strong>Propose pull request</strong>
              <span>2 kept</span>
            </div>
          </div>
        </div>

        {/* Risky spots table */}
        <section className="risky-table-section">
          <table className="risky-table">
            <thead>
              <tr>
                <th>RISKY SPOT</th>
                <th>WHY IT IS RISKY</th>
                <th>RESULT</th>
              </tr>
            </thead>
            <tbody>
              {riskySpots.map((r, i) => (
                <tr key={i}>
                  <td className="col-spot">
                    <code>{r.spot}</code>
                  </td>
                  <td className="col-why">{r.why}</td>
                  <td className="col-result">
                    <span className={`badge-result ${r.status}`}>{r.result}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* Example kept test snippet */}
        <section className="kept-example-section">
          <h3 className="section-label">ONE OF THE KEPT TESTS</h3>
          <div className="code-example-card">
            <pre>
              <code>
                {`def test_token_has_expected_length():
    # FlakeGuard generated test: records current behaviour at HEAD
    token = make_token(seed=42)
    assert len(token) == 16`}
              </code>
            </pre>
          </div>
          <p className="kept-disclaimer">
            These tests record how this code behaves today. They do not prove it is correct.
            If running twice behaves differently from run to run, the report says &ldquo;no
            evidence of flakiness in N runs&rdquo;.
          </p>
        </section>

        {/* Action row */}
        <div className="notest-actions">
          {!prOpened ? (
            <button
              className="btn-action-primary"
              onClick={handleOpenPR}
              disabled={opening}
            >
              {opening ? "Opening pull request..." : "Open pull request with kept tests"}
            </button>
          ) : (
            <div className="pr-opened-pill">
              ✓ Pull request opened on your fork (branch: <code>flakeguard/kept-tests</code>)
            </div>
          )}
          {onRunScanWithKept && (
            <button className="btn-action-secondary" onClick={onRunScanWithKept}>
              Scan with kept tests now
            </button>
          )}
          <span className="fork-note">Opens on your fork. Dropped tests are not included.</span>
        </div>
      </div>
    </div>
  );
};

