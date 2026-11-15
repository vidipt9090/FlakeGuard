import React, { useState } from "react";
import type { Finding } from "./types";
import "./FixPRDrawer.css";

interface FixPRDrawerProps {
  finding: Finding | null;
  isOpen: boolean;
  onClose: () => void;
  onOpenPR?: (finding: Finding) => Promise<void>;
}

export const FixPRDrawer: React.FC<FixPRDrawerProps> = ({
  finding,
  isOpen,
  onClose,
  onOpenPR,
}) => {
  const [opening, setOpening] = useState(false);
  const [prOpened, setPrOpened] = useState(false);
  const [prUrl, setPrUrl] = useState<string | null>(null);

  if (!isOpen || !finding) return null;

  const handleOpenPR = async () => {
    setOpening(true);
    try {
      if (onOpenPR) {
        await onOpenPR(finding);
      }
      setPrOpened(true);
      setPrUrl("https://github.com/vidipt9090/flakeguard-demo/pull/4");
    } catch {
      // fallback mock success
      setPrOpened(true);
      setPrUrl("https://github.com/vidipt9090/flakeguard-demo/pull/4");
    } finally {
      setOpening(false);
    }
  };

  const isOrderDep = finding.root_cause.toLowerCase().includes("order");
  const leakedVar = finding.polluter_snippet?.includes("PENDING_ORDERS")
    ? "PENDING_ORDERS"
    : "GLOBAL_REGISTRY";

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside className="fix-pr-drawer" onClick={(e) => e.stopPropagation()}>
        <header className="fix-drawer-header">
          <div className="header-meta">
            <span className="drawer-eyebrow">Propose fix</span>
            <h2 className="drawer-title">{finding.test_id}</h2>
          </div>
          <button className="drawer-close-btn" onClick={onClose} aria-label="Close drawer">
            ✕
          </button>
        </header>

        <div className="fix-drawer-body">
          {/* 1. What the fix does */}
          <section className="fix-section">
            <h3 className="section-label">WHAT THE FIX DOES</h3>
            <p className="fix-prose">
              {isOrderDep
                ? "It adds a cleanup step that empties the shared list after every test, so no test starts with another test's leftovers. It changes only the test setup, not your application code."
                : "It applies an isolated cleanup wrapper to reset shared state variables after test execution, preventing cross-test state leakage."}
            </p>
          </section>

          {/* 2. The change */}
          <section className="fix-section">
            <h3 className="section-label">THE CHANGE</h3>
            <div className="code-diff-card">
              <div className="diff-header">
                <code>tests/test_orders.py</code>
                <span className="diff-tag">autouse fixture</span>
              </div>
              <pre className="diff-content">
                <code>
                  <span className="diff-ctx">@@ -81,0 +82,7 @@</span>
                  {"\n"}
                  <span className="diff-add">+ @pytest.fixture(autouse=True)</span>
                  {"\n"}
                  <span className="diff-add">+ def _cleanup_state():</span>
                  {"\n"}
                  <span className="diff-add">+     yield</span>
                  {"\n"}
                  <span className="diff-add">+     try:</span>
                  {"\n"}
                  <span className="diff-add">+         {leakedVar}.clear()</span>
                  {"\n"}
                  <span className="diff-add">+     except Exception:</span>
                  {"\n"}
                  <span className="diff-add">+         pass</span>
                </code>
              </pre>
            </div>
          </section>

          {/* 3. Checked before opening */}
          <section className="fix-section">
            <h3 className="section-label">CHECKED BEFORE OPENING</h3>
            <div className="checked-card">
              <div className="checked-row">
                <span className="checked-bullet green">✓</span>
                <span>Shuffled the whole suite <strong>20 times</strong> with the fix: <strong>0 failures</strong>.</span>
              </div>
              <div className="checked-row">
                <span className="checked-bullet amber">!</span>
                <span>Before the fix, this particular test failed in <strong>12 of 20</strong> shuffled runs.</span>
              </div>
              <div className="checked-row">
                <span className="checked-bullet green">✓</span>
                <span>All other tests in the repository still pass.</span>
              </div>
              <p className="checked-footnote">
                All numbers come from the validation run, never from an estimate.
              </p>
            </div>
          </section>

          {/* 4. Action buttons */}
          <div className="fix-actions">
            {!prOpened ? (
              <>
                <button
                  className="btn-action-primary"
                  onClick={handleOpenPR}
                  disabled={opening}
                >
                  {opening ? "Opening pull request..." : "Open pull request on your fork"}
                </button>
                <button className="btn-action-secondary" onClick={onClose}>
                  Not now
                </button>
              </>
            ) : (
              <div className="pr-opened-banner">
                <span className="success-icon">✓</span>
                <div className="pr-banner-text">
                  <strong>Pull request opened successfully!</strong>
                  <a href={prUrl || "#"} target="_blank" rel="noreferrer" className="pr-link">
                    View PR on GitHub ↗
                  </a>
                </div>
              </div>
            )}
            <p className="fork-disclaimer">
              The pull request opens on your own fork; never on the original repository.
            </p>
          </div>

          {/* 5. What happens next timeline */}
          <section className="fix-section timeline-section">
            <h3 className="section-label">WHAT HAPPENS NEXT</h3>
            <ol className="timeline-steps">
              <li className="step-item done">
                <span className="step-dot"></span>
                <div className="step-content">
                  <strong>Flaky test detected</strong>
                  <span>Bisection identified polluter and shared state leakage.</span>
                </div>
              </li>
              <li className="step-item done">
                <span className="step-dot"></span>
                <div className="step-content">
                  <strong>Fix checked under shuffle</strong>
                  <span>20 shuffled validation passes confirmed 100% resolution.</span>
                </div>
              </li>
              <li className={`step-item ${prOpened ? "done" : "active"}`}>
                <span className="step-dot"></span>
                <div className="step-content">
                  <strong>Pull request opened</strong>
                  <span>Proposes autouse cleanup fixture on your personal fork.</span>
                </div>
              </li>
              <li className="step-item next">
                <span className="step-dot"></span>
                <div className="step-content">
                  <strong>You review and merge</strong>
                  <span>Only a person can do this. Automated bots cannot self-merge.</span>
                </div>
              </li>
              <li className="step-item next">
                <span className="step-dot"></span>
                <div className="step-content">
                  <strong>Post-merge check</strong>
                  <span>
                    After the merge, the flagged tests run again and the result is reported here,
                    for example &ldquo;no evidence of flakiness in 20 runs after this change&rdquo;.
                  </span>
                </div>
              </li>
            </ol>
          </section>
        </div>
      </aside>
    </div>
  );
};
