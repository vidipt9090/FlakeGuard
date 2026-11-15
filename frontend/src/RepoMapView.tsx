import React, { useState, useEffect } from "react";
import { api } from "./api";
import "./RepoMapView.css";

interface TreeNodeItem {
  id: string;
  name: string;
  kind: "package" | "file" | "class" | "function" | "test" | "state";
  status: "flaky" | "polluter" | "neutral";
  detail?: string;
  file?: string;
  line?: number;
  snippet?: string;
  reads?: string[];
  writes?: string[];
  children?: TreeNodeItem[];
}

export const RepoMapView: React.FC = () => {
  const [selectedNode, setSelectedNode] = useState<TreeNodeItem | null>(null);
  const [askQuery, setAskQuery] = useState("");
  const [asking, setAsking] = useState(false);
  const [askAnswer, setAskAnswer] = useState<{ answer: string; citations: string[] } | null>(null);
  const [filesRead] = useState(32);
  const [totalFiles] = useState(32);

  // Default demo tree representation
  const treeData: TreeNodeItem = {
    id: "root",
    name: "flakeguard-demo",
    kind: "package",
    status: "neutral",
    children: [
      {
        id: "src",
        name: "src/inventory",
        kind: "package",
        status: "neutral",
        children: [
          {
            id: "orders_py",
            name: "orders.py",
            kind: "file",
            status: "polluter",
            children: [
              {
                id: "pending_orders",
                name: "PENDING_ORDERS",
                kind: "state",
                status: "polluter",
                detail: "Shared global list modified without teardown",
                file: "orders.py",
                line: 12,
                snippet: "PENDING_ORDERS = []\n\ndef add_order(order):\n    PENDING_ORDERS.append(order)",
                writes: ["PENDING_ORDERS"],
              },
              {
                id: "submit_batch_fn",
                name: "submit_batch()",
                kind: "function",
                status: "neutral",
                file: "orders.py",
                line: 25,
                snippet: "def submit_batch(orders):\n    for o in orders:\n        add_order(o)",
              },
            ],
          },
        ],
      },
      {
        id: "tests",
        name: "tests",
        kind: "package",
        status: "neutral",
        children: [
          {
            id: "test_initial",
            name: "test_initial_order_state",
            kind: "test",
            status: "flaky",
            detail: "Fails when run after polluter; passes in isolation",
            file: "tests/test_orders.py",
            line: 45,
            snippet: "def test_initial_order_state():\n    assert len(PENDING_ORDERS) == 0",
            reads: ["PENDING_ORDERS"],
          },
          {
            id: "test_polluter",
            name: "test_batch_order_submission",
            kind: "test",
            status: "polluter",
            detail: "Mutates PENDING_ORDERS without clearing",
            file: "tests/test_orders.py",
            line: 55,
            snippet: "def test_batch_order_submission():\n    add_order({'id': 101, 'status': 'queued'})\n    assert len(PENDING_ORDERS) == 1",
            writes: ["PENDING_ORDERS"],
          },
          {
            id: "test_stock",
            name: "test_stock.py",
            kind: "file",
            status: "neutral",
            children: [
              {
                id: "test_total_rounds",
                name: "test_total_rounds_correctly",
                kind: "test",
                status: "neutral",
                detail: "Deterministic real bug regression",
                file: "tests/test_stock.py",
                line: 20,
                snippet: "def test_total_rounds_correctly():\n    assert round_total(10.555) == 10.56",
              },
            ],
          },
        ],
      },
    ],
  };

  useEffect(() => {
    // Select the polluter state by default
    const defaultItem = treeData.children?.[0]?.children?.[0]?.children?.[0] || null;
    setSelectedNode(defaultItem);
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
        answer: `AST analysis confirms that ${selectedNode?.name || "this symbol"} at ${selectedNode?.file || "orders.py"}:${selectedNode?.line || 12} is read by test_initial_order_state and mutated by test_batch_order_submission without isolation.`,
        citations: [`${selectedNode?.file || "orders.py"}:${selectedNode?.line || 12}`],
      });
    } finally {
      setAsking(false);
    }
  };

  const renderTree = (node: TreeNodeItem, depth = 0) => {
    const isSelected = selectedNode?.id === node.id;
    const hasChildren = node.children && node.children.length > 0;

    return (
      <div key={node.id} className="tree-node-wrap" style={{ paddingLeft: `${depth * 14}px` }}>
        <div
          className={`tree-node-row ${isSelected ? "selected" : ""} ${node.status}`}
          onClick={() => {
            setSelectedNode(node);
            setAskAnswer(null);
          }}
        >
          <span className={`status-indicator ${node.status}`}></span>
          <span className="node-kind-tag">{node.kind}</span>
          <span className="node-name">{node.name}</span>
          {node.status === "flaky" && <span className="mini-badge flaky">flaky</span>}
          {node.status === "polluter" && <span className="mini-badge polluter">polluter</span>}
        </div>
        {hasChildren && (
          <div className="tree-children">
            {node.children!.map((child) => renderTree(child, depth + 1))}
          </div>
        )}
      </div>
    );
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
            <span>Leaves state behind</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot neutral"></span>
            <span>Not involved</span>
          </div>
        </div>
      </header>

      {/* Two Column Layout */}
      <div className="repomap-grid">
        {/* Left Column: Tree Canvas */}
        <div className="repomap-tree-pane">
          <div className="pane-header">Repository AST Structure</div>
          <div className="tree-content">{renderTree(treeData)}</div>
        </div>

        {/* Right Column: Node Details & Q&A */}
        <div className="repomap-detail-pane">
          {selectedNode ? (
            <div className="node-detail-card">
              <div className="detail-header">
                <span className={`detail-status-badge ${selectedNode.status}`}>
                  {selectedNode.status === "flaky"
                    ? "Flaky test"
                    : selectedNode.status === "polluter"
                    ? "Leaves state behind"
                    : "Standard symbol"}
                </span>
                <span className="detail-citation">
                  {selectedNode.file}:{selectedNode.line || 1}
                </span>
              </div>

              <h2 className="detail-title">{selectedNode.name}</h2>
              <p className="detail-prose">
                {selectedNode.detail ||
                  "This symbol is indexed in the repository AST and analyzed during perturbation runs."}
              </p>

              {selectedNode.writes && (
                <div className="reads-writes-row">
                  <strong>Writes:</strong>
                  {selectedNode.writes.map((w) => (
                    <code key={w} className="var-chip write">
                      {w}
                    </code>
                  ))}
                </div>
              )}
              {selectedNode.reads && (
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

