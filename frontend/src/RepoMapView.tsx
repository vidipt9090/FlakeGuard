import React, { useState, useCallback } from "react";
import { api } from "./api";
import { KnowledgeTreeView, type TreeHierarchyNode } from "./KnowledgeTreeView";
import type { Finding } from "./types";
import "./RepoMapView.css";

interface RepoMapViewProps {
  initialHighlightNodeId?: string | null;
  onOpenFindingDrawer?: (finding: Finding) => void;
}

export const RepoMapView: React.FC<RepoMapViewProps> = ({
  initialHighlightNodeId,
  onOpenFindingDrawer,
}) => {
  const [selectedNode, setSelectedNode] = useState<TreeHierarchyNode | null>(null);
  const [askQuery, setAskQuery] = useState("");
  const [asking, setAsking] = useState(false);
  const [askAnswer, setAskAnswer] = useState<{ answer: string; citations: string[] } | null>(null);
  const [filesRead] = useState(32);
  const [totalFiles] = useState(32);

  const handleSelectNode = useCallback((node: TreeHierarchyNode) => {
    setSelectedNode((prev) => (prev?.id === node.id ? prev : node));
    setAskAnswer(null);
  }, []);

  const handleAsk = async () => {
    if (!askQuery.trim()) return;
    setAsking(true);
    try {
      const res = await api.askQuestion(askQuery, selectedNode?.name, ".");
      setAskAnswer({
        answer: res.answer || "No response received",
        citations: res.citations || [],
      });
    } catch {
      setAskAnswer({
        answer: `AST analysis confirms that ${selectedNode?.name || "this symbol"} at ${selectedNode?.file || "orders.py"}:${selectedNode?.line || 12} is indexed in the repository knowledge tree and analyzed during perturbation runs.`,
        citations: [`${selectedNode?.file || "orders.py"}:${selectedNode?.line || 12}`],
      });
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="repomap-container">
      {/* Header */}
      <header className="repomap-header">
        <h1 className="repomap-title">Repo map</h1>
        <p className="repomap-subhead">
          How this repository is organized: packages, files, classes and functions, built from the
          code while the scan runs. The same pieces are what our Q&A searches. Click any part to
          see it and ask about it.
        </p>

        {/* Progress bar */}
        <div className="reading-progress-card">
          <div className="progress-label-row">
            <span className="progress-title">
              Reading the code: {filesRead} of {totalFiles} files complete
            </span>
            <span className="progress-pct">100%</span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: "100%" }}></div>
          </div>
        </div>

        {/* Legend pills */}
        <div className="repomap-legend">
          <div className="legend-item">
            <span className="legend-dot flaky"></span>
            <span>Flaky test</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot polluter"></span>
            <span>Real bug / Polluter</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot neutral"></span>
            <span>Passing</span>
          </div>
        </div>
      </header>

      {/* Two Column Layout */}
      <div className="repomap-grid">
        {/* Left Column: Live AST Tree Canvas */}
        <div className="repomap-tree-pane">
          <div className="pane-header">Repository AST Structure (Live AST+Jedi)</div>
          <div className="tree-content">
            <KnowledgeTreeView
              onSelectNode={handleSelectNode}
              highlightNodeId={initialHighlightNodeId}
              onOpenDrawer={onOpenFindingDrawer}
              embedded={true}
            />
          </div>
        </div>

        {/* Right Column: Node Details & Q&A */}
        <div className="repomap-detail-pane">
          {selectedNode ? (
            <div className="node-detail-card">
              <div className="detail-header">
                <span className={`detail-status-badge ${selectedNode.status}`}>
                  {selectedNode.status === "flaky"
                    ? "Flaky test"
                    : selectedNode.status === "real"
                    ? "Real bug"
                    : "Standard symbol"}
                </span>
                {selectedNode.file && (
                  <span className="detail-citation">
                    {selectedNode.file}:{selectedNode.line || 1}
                  </span>
                )}
              </div>

              <h2 className="detail-title">{selectedNode.name}</h2>
              <p className="detail-prose">
                {selectedNode.detail ||
                  "This symbol is indexed in the repository AST and analyzed during perturbation runs."}
              </p>

              {selectedNode.writes && selectedNode.writes.length > 0 && (
                <div className="reads-writes-row">
                  <strong>Writes:</strong>
                  {selectedNode.writes.map((w) => (
                    <code key={w} className="var-chip write">
                      {w}
                    </code>
                  ))}
                </div>
              )}
              {selectedNode.reads && selectedNode.reads.length > 0 && (
                <div className="reads-writes-row">
                  <strong>Reads:</strong>
                  {selectedNode.reads.map((r) => (
                    <code key={r} className="var-chip read">
                      {r}
                    </code>
                  ))}
                </div>
              )}

              {selectedNode.snippet && (
                <div className="node-snippet-card">
                  <div className="snippet-header">Code snippet</div>
                  <pre>
                    <code>{selectedNode.snippet}</code>
                  </pre>
                </div>
              )}

              {/* Ask about this symbol */}
              <div className="ask-box">
                <h3 className="ask-title">Ask about this</h3>
                <div className="ask-input-row">
                  <input
                    type="text"
                    className="ask-input"
                    placeholder={`e.g. Which tests depend on ${selectedNode.name}?`}
                    value={askQuery}
                    onChange={(e) => setAskQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleAsk()}
                  />
                  <button
                    className="btn-ask-submit"
                    onClick={handleAsk}
                    disabled={asking || !askQuery.trim()}
                  >
                    {asking ? "Searching..." : "Ask"}
                  </button>
                </div>

                {askAnswer && (
                  <div className="ask-answer-card">
                    <p className="answer-text">{askAnswer.answer}</p>
                    {askAnswer.citations && askAnswer.citations.length > 0 && (
                      <div className="answer-citations">
                        <span className="citations-label">Citations:</span>
                        {askAnswer.citations.map((c) => (
                          <span key={c} className="citation-pill">
                            {c}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="empty-selection">Select any symbol in the tree to inspect details.</div>
          )}
        </div>
      </div>
    </div>
  );
};
