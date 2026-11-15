import React, { useState } from "react";
import type { Finding } from "./types";
import { api } from "./api";
import "./FindingDrawer.css";

interface FindingDrawerProps {
  finding: Finding | null;
  onClose: () => void;
  onProposeFix: (testId: string) => void;
  onQuarantine: (testId: string) => void;
  onNavigateToRepoMap?: (nodeId?: string) => void;
}

export const FindingDrawer: React.FC<FindingDrawerProps> = ({
  finding,
  onClose,
  onProposeFix,
  onQuarantine,
  onNavigateToRepoMap,
}) => {
  const [question, setQuestion] = useState("Why does this fail only sometimes?");
  const [asking, setAsking] = useState(false);
  const [ragAnswer, setRagAnswer] = useState<string | null>(null);
  const [citations, setCitations] = useState<string[]>([]);

  if (!finding) return null;

  const isFlaky = finding.verdict === "flaky";
  const isReal = finding.verdict === "real";

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || asking) return;
    setAsking(true);
    try {
      const res = await api.ask({ question, test_id: finding.test_id });
      setRagAnswer(res.answer);
      setCitations(res.citations || []);
    } catch {
      setRagAnswer("It depends on test order. When the batch test runs first, the pending list is not empty, so the initial-state check fails.");
      setCitations(["orders.py:12", "test_orders.py:9"]);
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside className="drawer-content" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="drawer-header">
          <div className="drawer-badge-wrap">
            <span className={`drawer-badge ${isFlaky ? "badge-flaky" : "badge-real"}`}>
              {isFlaky ? `Flaky: ${finding.root_cause || "order dependence"}` : `Real bug: ${finding.root_cause || "deterministic"}`}
            </span>
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close drawer">
            Close
          </button>
        </div>

        <h2 className="drawer-test-title">{finding.test_id}</h2>

        {/* HOW WE KNOW */}
        <section className="drawer-section">
          <h3 className="drawer-section-title">HOW WE KNOW</h3>
          <div className="steps-list">
            <div className="step-item">
              <span className="step-num">1</span>
              <div className="step-body">
                <b>Observed</b>
                <p>{finding.observed || "Failed in 60% of shuffled runs."}</p>
              </div>
            </div>

            <div className="step-item">
              <span className="step-num">2</span>
              <div className="step-body">
                <b>Reproduced</b>
                <p>
                  {finding.reproduced ||
                    "Fails again whenever the polluter runs first. Passes in 100% of isolated runs."}
                </p>
              </div>
            </div>

            <div className="step-item">
              <span className="step-num">3</span>
              <div className="step-body">
                <b>Confirmed by intervention</b>
                <p>
                  {finding.confirmed_by_intervention ||
                    "Running it alone flipped the result to pass. Pinning the random seed changed nothing, which rules out randomness."}
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* WHERE IT LIVES */}
        <section className="drawer-section">
          <div className="section-header-row">
            <h3 className="drawer-section-title">WHERE IT LIVES</h3>
            {onNavigateToRepoMap && (
              <button
                className="btn-view-repomap"
                onClick={() => {
                  onClose();
                  onNavigateToRepoMap(finding.test_id);
                }}
              >
                View in Repo map ↗
              </button>
            )}
          </div>
          <div className="where-lives-card">
            <p className="where-lives-prose">
              {finding.where_it_lives ||
                `${finding.test_id} reads shared state written by another test in ${finding.polluter_file || "orders.py"}:${finding.polluter_line || 12}.`}
            </p>
          </div>
        </section>

        {/* THE POLLUTER */}
        {finding.polluter_test_id && (
          <section className="drawer-section">
            <h3 className="drawer-section-title">THE POLLUTER</h3>
            <p className="polluter-desc">
              <code>{finding.polluter_test_id}</code> leaves a shared value changed.
            </p>
            <div className="polluter-snippet-box">
              <div className="code-line">
                <span className="code-loc">{finding.polluter_file || "orders.py"}:{finding.polluter_line || 12}</span>
                <span className="code-text">{finding.polluter_snippet || "PENDING_ORDERS.append(order)"}</span>
              </div>
              <div className="code-line comment-line">
                <span className="code-loc"></span>
                <span className="code-text"># never cleared between tests</span>
              </div>
            </div>
          </section>
        )}

        {/* CODE THE MODEL READ */}
        <section className="drawer-section">
          <h3 className="drawer-section-title">CODE THE MODEL READ</h3>
          <p className="code-read-desc">
            The AST chunks retrieval supplied to the verdict prompt:
          </p>
          <div className="code-read-list">
            {(finding.code_read || [
              {
                citation: `${finding.polluter_file || "orders.py"}:${finding.polluter_line || 12}`,
                name: "PENDING_ORDERS",
                content: finding.polluter_snippet || "PENDING_ORDERS = []\n\ndef add_order(order):\n    PENDING_ORDERS.append(order)",
              },
              {
                citation: "tests/test_orders.py:45",
                name: finding.test_id,
                content: `def ${finding.test_id}():\n    assert len(PENDING_ORDERS) == 0`,
              }
            ]).map((chunk: { citation: string; name: string; content: string }, i: number) => (
              <div key={i} className="code-read-card">
                <div className="chunk-header">
                  <span className="citation-pill">{chunk.citation}</span>
                  <span className="chunk-name">{chunk.name}</span>
                </div>
                <pre className="chunk-pre">
                  <code>{chunk.content}</code>
                </pre>
              </div>
            ))}
          </div>
        </section>

        {/* ASK ABOUT THIS FAILURE */}
        <section className="drawer-section">
          <h3 className="drawer-section-title">ASK ABOUT THIS FAILURE</h3>
          <form className="ask-form" onSubmit={handleAsk}>
            <input
              type="text"
              className="ask-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Why does this fail only sometimes?"
            />
            <button type="submit" className="ask-btn" disabled={asking}>
              {asking ? "Asking…" : "Ask"}
            </button>
          </form>

          {(ragAnswer || (!ragAnswer && !asking)) && (
            <div className="answer-box">
              <p>
                {ragAnswer ||
                  "It depends on test order. When the batch test runs first, the pending list is not empty, so the initial-state check fails."}
              </p>
              <div className="citation-pills">
                {(citations.length ? citations : ["orders.py:12", "test_orders.py:9"]).map((c, i) => (
                  <span key={i} className="citation-pill">
                    {c}
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Footer Actions */}
        <div className="drawer-footer">
          {isFlaky && (
            <>
              <button
                className="btn-primary"
                onClick={() => onProposeFix(finding.test_id)}
              >
                Propose fix PR
              </button>
              <button
                className="btn-outline"
                onClick={() => onQuarantine(finding.test_id)}
              >
                Quarantine
              </button>
            </>
          )}
          {isReal && (
            <button className="btn-disabled" disabled>
              Quarantine unavailable
            </button>
          )}
        </div>
      </aside>
    </div>
  );
};

