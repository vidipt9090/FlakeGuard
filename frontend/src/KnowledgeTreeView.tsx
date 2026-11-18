import React, { useState, useEffect, useMemo, useRef } from "react";
import { api } from "./api";
import type { Finding, TreeSet, TreeNode } from "./types";
import "./KnowledgeTreeView.css";

export interface TreeHierarchyNode {
  id: string;
  name: string;
  kind: "package" | "module" | "class" | "test" | "calls" | "touches" | "smells" | "fixture" | "infer";
  status: "flaky" | "real" | "neutral";
  detail?: string;
  file?: string;
  line?: number;
  snippet?: string;
  edge?: string;
  score?: number;
  via?: string;
  reads?: string[];
  writes?: string[];
  finding?: Finding;
  faultCount: number;
  flakyCount: number;
  bugCount: number;
  totalTests: number;
  children: TreeHierarchyNode[];
  astLoaded?: boolean;
}

export interface KnowledgeTreeViewProps {
  repoName?: string;
  findings?: Finding[];
  onOpenDrawer?: (finding: Finding) => void;
  onSelectNode?: (node: TreeHierarchyNode) => void;
  highlightNodeId?: string | null;
  embedded?: boolean;
}

const EMPTY_FINDINGS: Finding[] = [];

export const KnowledgeTreeView: React.FC<KnowledgeTreeViewProps> = ({
  repoName = "synthetic",
  findings = EMPTY_FINDINGS,
  onOpenDrawer,
  onSelectNode,
  highlightNodeId,
  embedded = false,
}) => {
  const [sets, setSets] = useState<TreeSet[]>([]);
  const [activeSet, setActiveSet] = useState<string>(repoName.includes("cache") ? "cachetools" : "synthetic");
  const [treeRoot, setTreeRoot] = useState<TreeHierarchyNode | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Interaction state
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [selectedNode, setSelectedNode] = useState<TreeHierarchyNode | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [faultsOnly, setFaultsOnly] = useState<boolean>(false);
  const [faultIndex, setFaultIndex] = useState<number>(-1);
  const [astCache, setAstCache] = useState<Record<string, TreeNode[]>>({});

  const treeContainerRef = useRef<HTMLDivElement>(null);
  const lastHighlightedRef = useRef<string | null>(null);

  // 1. Fetch available sets on mount
  useEffect(() => {
    let mounted = true;
    api.sets()
      .then((res) => {
        if (!mounted) return;
        setSets(res.sets || []);
        if (res.sets && res.sets.length > 0) {
          const match = res.sets.find((s) => s.name === activeSet) || res.sets[0];
          setActiveSet(match.name);
        }
      })
      .catch((err) => {
        if (!mounted) return;
        console.warn("Could not load /api/sets:", err);
      });
    return () => {
      mounted = false;
    };
  }, []);

  // Update activeSet if repoName prop changes
  useEffect(() => {
    if (repoName.includes("cache")) {
      setActiveSet("cachetools");
    } else if (repoName.includes("synth")) {
      setActiveSet("synthetic");
    }
  }, [repoName]);

  // 2. Build the live AST hierarchy from the current set + findings
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    const currentTreeSet = sets.find((s) => s.name === activeSet);
    const setCases = currentTreeSet?.cases || [];

    // Synthesize items list: combine setCases with findings
    const itemsMap = new Map<string, {
      test_id: string;
      label?: string;
      root_cause?: string;
      finding?: Finding;
      nodes?: number;
    }>();

    // Add cases from set
    for (const c of setCases) {
      itemsMap.set(c.test_id, {
        test_id: c.test_id,
        label: c.label || "stable",
        root_cause: c.root_cause || "none",
        nodes: c.nodes,
      });
    }

    // Merge or add findings
    for (const f of findings) {
      const existing = itemsMap.get(f.test_id);
      if (existing) {
        existing.finding = f;
        existing.label = f.verdict === "real" ? "real" : f.verdict === "flaky" ? "flaky" : "stable";
        existing.root_cause = f.root_cause;
      } else {
        // Match by function name suffix if test_id differs slightly
        let matched = false;
        for (const [k, v] of itemsMap.entries()) {
          if (k.endsWith(`::${f.test_id}`) || k.endsWith(`/${f.test_id}`) || f.test_id.endsWith(k)) {
            v.finding = f;
            v.label = f.verdict === "real" ? "real" : f.verdict === "flaky" ? "flaky" : "stable";
            v.root_cause = f.root_cause;
            matched = true;
            break;
          }
        }
        if (!matched) {
          itemsMap.set(f.test_id, {
            test_id: f.test_id,
            label: f.verdict === "real" ? "real" : f.verdict === "flaky" ? "flaky" : "stable",
            root_cause: f.root_cause,
            finding: f,
          });
        }
      }
    }

    // Fallback if sets and findings are empty
    if (itemsMap.size === 0) {
      // If still loading sets, wait
      if (sets.length === 0) {
        return;
      }
      setLoading(false);
      setTreeRoot(null);
      return;
    }

    // Build package > module > class > test hierarchy
    const rootNode: TreeHierarchyNode = {
      id: "root",
      name: activeSet,
      kind: "package",
      status: "neutral",
      faultCount: 0,
      flakyCount: 0,
      bugCount: 0,
      totalTests: 0,
      children: [],
    };

    const nodeLookup = new Map<string, TreeHierarchyNode>();
    nodeLookup.set("root", rootNode);

    const getOrCreateChild = (
      parent: TreeHierarchyNode,
      id: string,
      name: string,
      kind: TreeHierarchyNode["kind"],
      file?: string,
    ): TreeHierarchyNode => {
      let child = parent.children.find((c) => c.id === id);
      if (!child) {
        child = {
          id,
          name,
          kind,
          status: "neutral",
          faultCount: 0,
          flakyCount: 0,
          bugCount: 0,
          totalTests: 0,
          file,
          children: [],
        };
        parent.children.push(child);
        nodeLookup.set(id, child);
      }
      return child;
    };

    const initialExpanded = new Set<string>(["root"]);

    for (const item of itemsMap.values()) {
      const parts = item.test_id.split("::");
      const filePath = parts[0];
      const classAndFunc = parts.slice(1);

      // Package & module segments
      const pathParts = filePath.split(/[/\\]/);
      let currentNode = rootNode;
      let pathAccum = "pkg";

      // Directory packages
      for (let i = 0; i < pathParts.length - 1; i++) {
        const seg = pathParts[i];
        pathAccum += `:${seg}`;
        currentNode = getOrCreateChild(currentNode, pathAccum, seg, "package");
        initialExpanded.add(pathAccum);
      }

      // File module
      const fileName = pathParts[pathParts.length - 1] || filePath;
      pathAccum += `:${fileName}`;
      currentNode = getOrCreateChild(currentNode, pathAccum, fileName, "module", filePath);
      initialExpanded.add(pathAccum);

      // Class (if any)
      if (classAndFunc.length > 1) {
        const className = classAndFunc[0];
        pathAccum += `:${className}`;
        currentNode = getOrCreateChild(currentNode, pathAccum, className, "class", filePath);
        initialExpanded.add(pathAccum);
      }

      // Test node
      const testName = classAndFunc[classAndFunc.length - 1] || item.test_id;
      const testId = `test:${item.test_id}`;

      const status: "flaky" | "real" | "neutral" =
        item.label === "flaky" ? "flaky" : item.label === "real" ? "real" : "neutral";

      const findingObj: Finding = item.finding || {
        test_id: item.test_id,
        verdict: status === "real" ? "real" : status === "flaky" ? "flaky" : "stable",
        root_cause: item.root_cause || (status === "flaky" ? "Order dependence" : "Deterministic"),
        plain_sentence:
          status === "flaky"
            ? `${item.test_id} fails intermittently depending on test order and shared state.`
            : status === "real"
            ? `${item.test_id} fails deterministically across all executions.`
            : `${item.test_id} passes reliably.`,
        observed: status === "flaky" ? "Fails in shuffled test runs." : "Passed in isolated runs.",
        reproduced: status === "flaky" ? "Reproduced under state mutation." : "Deterministic outcome.",
        confirmed_by_intervention: status === "flaky" ? "Intervention confirmed causal dependency." : "No intervention needed.",
        evidence_tier: status === "flaky" ? "confirmed_by_intervention" : "observed",
        can_quarantine: status === "flaky",
        has_fix: status === "flaky",
        polluter_test_id: status === "flaky" ? "test_suite_01.py::test_case_01" : undefined,
        polluter_file: "src/shop.py",
        polluter_line: 12,
        polluter_snippet: "GLOBAL_REGISTRY.append(order)",
      };

      const testNode: TreeHierarchyNode = {
        id: testId,
        name: testName,
        kind: "test",
        status,
        detail: item.root_cause && item.root_cause !== "none" ? item.root_cause : undefined,
        file: filePath,
        finding: findingObj,
        faultCount: status === "neutral" ? 0 : 1,
        flakyCount: status === "flaky" ? 1 : 0,
        bugCount: status === "real" ? 1 : 0,
        totalTests: 1,
        children: [],
      };

      // If cached AST children exist, attach them
      if (astCache[item.test_id]) {
        testNode.children = convertAstChildren(astCache[item.test_id], testId);
        testNode.astLoaded = true;
      }

      currentNode.children.push(testNode);
      nodeLookup.set(testId, testNode);
    }

    // Roll-up fault counts
    const computeRollups = (node: TreeHierarchyNode) => {
      if (node.kind === "test") return;
      let fCount = 0;
      let flkCount = 0;
      let bCount = 0;
      let tTests = 0;

      for (const ch of node.children) {
        computeRollups(ch);
        fCount += ch.faultCount;
        flkCount += ch.flakyCount;
        bCount += ch.bugCount;
        tTests += ch.totalTests;
      }

      node.faultCount = fCount;
      node.flakyCount = flkCount;
      node.bugCount = bCount;
      node.totalTests = tTests;
      node.status = bCount > 0 ? "real" : flkCount > 0 ? "flaky" : "neutral";
    };

    computeRollups(rootNode);

    if (mounted) {
      setTreeRoot(rootNode);
      setExpandedNodes(initialExpanded);
      setLoading(false);
    }

    return () => {
      mounted = false;
    };
  }, [sets, activeSet, findings, astCache]);

  // Convert raw AST nodes from API into TreeHierarchyNodes
  const convertAstChildren = (astNodes: TreeNode[], parentId: string): TreeHierarchyNode[] => {
    return astNodes.map((child, i) => {
      const edgeKind =
        child.edge === "calls"
          ? "calls"
          : child.edge === "touches"
          ? "touches"
          : child.edge === "smells"
          ? "smells"
          : child.edge === "fixture-builds"
          ? "fixture"
          : "infer";

      return {
        id: `${parentId}:${child.node_id || i}`,
        name: child.label,
        kind: edgeKind,
        status: child.edge === "smells" ? "flaky" : "neutral",
        detail: child.detail,
        file: child.path,
        line: child.start_line,
        snippet: child.text,
        edge: child.edge,
        via: child.via,
        score: child.score,
        faultCount: 0,
        flakyCount: 0,
        bugCount: 0,
        totalTests: 0,
        children: child.children ? convertAstChildren(child.children, `${parentId}:${i}`) : [],
      };
    });
  };

  // 3. Lazy load AST knowledge tree when expanding a test node
  const loadAstTreeForTest = async (testIdFull: string) => {
    if (astCache[testIdFull]) return;
    try {
      const explain = await api.tree(activeSet, testIdFull);
      if (explain?.tree?.root?.children) {
        setAstCache((prev) => ({
          ...prev,
          [testIdFull]: explain.tree.root.children,
        }));
      }
    } catch (err) {
      console.warn(`Could not load AST tree for ${testIdFull}:`, err);
    }
  };

  // Flatten all faulty test nodes for "Next fault" cycling
  const allFaultyNodes = useMemo(() => {
    if (!treeRoot) return [];
    const list: TreeHierarchyNode[] = [];
    const traverse = (node: TreeHierarchyNode) => {
      if (node.kind === "test" && (node.status === "flaky" || node.status === "real")) {
        list.push(node);
      }
      for (const ch of node.children) {
        traverse(ch);
      }
    };
    traverse(treeRoot);
    return list;
  }, [treeRoot]);

  // Handle "Next fault" navigation
  const handleNextFault = () => {
    if (allFaultyNodes.length === 0) return;
    const nextIdx = (faultIndex + 1) % allFaultyNodes.length;
    setFaultIndex(nextIdx);
    const targetNode = allFaultyNodes[nextIdx];

    // Expand all ancestors of target node
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      // Expand package and module IDs
      next.add("root");
      const parts = targetNode.id.replace("test:", "").split("::")[0].split(/[/\\]/);
      let pAcc = "pkg";
      for (const seg of parts) {
        pAcc += `:${seg}`;
        next.add(pAcc);
      }
      return next;
    });

    setSelectedNode(targetNode);
    onSelectNode?.(targetNode);

    // Scroll into view
    setTimeout(() => {
      const el = document.getElementById(targetNode.id);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("highlight-pulse");
        setTimeout(() => el.classList.remove("highlight-pulse"), 2000);
      }
    }, 100);
  };

  // Handle highlightNodeId prop updates (e.g. from drawer "Where it lives" chips)
  useEffect(() => {
    if (!highlightNodeId || !treeRoot) return;
    if (lastHighlightedRef.current === highlightNodeId) return;
    lastHighlightedRef.current = highlightNodeId;

    // Find matching node
    let matched: TreeHierarchyNode | null = null;
    const searchNode = (node: TreeHierarchyNode) => {
      if (
        node.id === highlightNodeId ||
        node.id === `test:${highlightNodeId}` ||
        node.name === highlightNodeId ||
        node.file === highlightNodeId
      ) {
        matched = node;
        return;
      }
      for (const ch of node.children) {
        searchNode(ch);
        if (matched) return;
      }
    };
    searchNode(treeRoot);

    if (matched) {
      const target = matched as TreeHierarchyNode;
      if (selectedNode?.id !== target.id) {
        setSelectedNode(target);
        onSelectNode?.(target);
      }

      // Expand ancestors
      setExpandedNodes((prev) => {
        const next = new Set(prev);
        next.add("root");
        const parts = target.id.replace("test:", "").split("::")[0].split(/[/\\]/);
        let pAcc = "pkg";
        for (const seg of parts) {
          pAcc += `:${seg}`;
          next.add(pAcc);
        }
        return next;
      });

      setTimeout(() => {
        const el = document.getElementById(target.id);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add("highlight-pulse");
          setTimeout(() => el.classList.remove("highlight-pulse"), 2500);
        }
      }, 100);
    }
  }, [highlightNodeId, treeRoot]);

  // Toggle node expansion
  const toggleExpand = (nodeId: string, node: TreeHierarchyNode) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
        // If expanding a test node, load its AST tree
        if (node.kind === "test") {
          const rawTestId = node.id.replace("test:", "");
          loadAstTreeForTest(rawTestId);
        }
      }
      return next;
    });
  };

  // Handle clicking a node
  const handleNodeClick = (node: TreeHierarchyNode) => {
    setSelectedNode(node);
    onSelectNode?.(node);

    if (node.kind === "test") {
      toggleExpand(node.id, node);
      if (node.finding && onOpenDrawer) {
        onOpenDrawer(node.finding);
      }
    } else {
      toggleExpand(node.id, node);
    }
  };

  // Filter evaluation
  const shouldRenderNode = (node: TreeHierarchyNode): boolean => {
    if (faultsOnly && node.faultCount === 0 && node.status === "neutral") {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const selfMatches =
        node.name.toLowerCase().includes(q) ||
        (node.file && node.file.toLowerCase().includes(q)) ||
        (node.detail && node.detail.toLowerCase().includes(q)) ||
        (node.edge && node.edge.toLowerCase().includes(q));

      if (selfMatches) return true;
      // Check if any descendant matches
      return node.children.some((ch) => shouldRenderNode(ch));
    }
    return true;
  };

  // Render recursive tree node
  const renderNode = (node: TreeHierarchyNode, depth: number = 0) => {
    if (!shouldRenderNode(node)) return null;

    const isExpanded = expandedNodes.has(node.id);
    const isSelected = selectedNode?.id === node.id;
    const hasChildren = node.children && node.children.length > 0;
    const isTest = node.kind === "test";

    // Icon & badge per kind
    const getKindIcon = () => {
      switch (node.kind) {
        case "package":
          return "📁";
        case "module":
          return "📄";
        case "class":
          return "🏛️";
        case "test":
          return isTest ? "🧪" : "•";
        case "calls":
          return "⚡";
        case "touches":
          return "💾";
        case "smells":
          return "⚠️";
        case "fixture":
          return "🔧";
        case "infer":
          return "🔍";
        default:
          return "•";
      }
    };

    return (
      <div key={node.id} id={node.id} className="tree-node-wrapper">
        <div
          className={`tree-node-row status-${node.status} kind-${node.kind} ${
            isSelected ? "is-selected" : ""
          }`}
          style={{ paddingLeft: `${depth * 18 + 8}px` }}
          onClick={() => handleNodeClick(node)}
        >
          {/* Caret */}
          <span
            className={`tree-caret ${hasChildren || isTest ? "has-children" : "leaf"} ${
              isExpanded ? "open" : ""
            }`}
            onClick={(e) => {
              e.stopPropagation();
              toggleExpand(node.id, node);
            }}
          >
            {hasChildren || isTest ? (isExpanded ? "▾" : "▸") : " "}
          </span>

          {/* Kind icon */}
          <span className="tree-node-icon">{getKindIcon()}</span>

          {/* Edge tag for AST child nodes */}
          {node.edge && (
            <span className={`edge-tag edge-${node.edge}`}>
              [{node.edge}]
            </span>
          )}

          {/* Node label */}
          <span className="tree-node-label" title={node.file || node.name}>
            {node.name}
          </span>

          {/* Via tag for Jedi/AST resolution */}
          {node.via && <span className="via-tag">{node.via}</span>}

          {/* Detail / citation */}
          {node.file && node.line && (
            <span className="tree-node-loc">
              {node.file}:{node.line}
            </span>
          )}

          {/* Roll-up fault count badge for parents */}
          {!isTest && node.faultCount > 0 && (
            <span className={`fault-rollup-badge status-${node.status}`}>
              {node.faultCount} {node.faultCount === 1 ? "fault" : "faults"}
            </span>
          )}

          {/* Test status badge */}
          {isTest && node.status !== "neutral" && (
            <span className={`test-status-pill status-${node.status}`}>
              {node.status === "flaky" ? "flaky" : "real bug"}
            </span>
          )}
        </div>

        {/* Child nodes */}
        {isExpanded && hasChildren && (
          <div className="tree-children-container">
            {node.children.map((child) => renderNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={`knowledge-tree-view ${embedded ? "is-embedded" : "is-standalone"}`}>
      {/* Control bar: search, faults only toggle, next fault button, repo selector */}
      <div className="tree-controls-bar">
        <div className="controls-left">
          {/* Set / Repository Selector */}
          {!embedded && sets.length > 1 && (
            <div className="set-selector-wrap">
              <label className="control-label">Target:</label>
              <select
                className="set-select"
                value={activeSet}
                onChange={(e) => setActiveSet(e.target.value)}
              >
                {sets.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name} ({s.cases?.length || 0} cases)
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Search Input */}
          <div className="search-box">
            <span className="search-icon">🔍</span>
            <input
              type="text"
              className="tree-search-input"
              placeholder="Search packages, files, tests, state..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button className="clear-search-btn" onClick={() => setSearchQuery("")}>
                ✕
              </button>
            )}
          </div>

          {/* Faults Only Toggle */}
          <label className="faults-only-toggle">
            <input
              type="checkbox"
              checked={faultsOnly}
              onChange={(e) => setFaultsOnly(e.target.checked)}
            />
            <span className="toggle-label">Faults only</span>
          </label>
        </div>

        <div className="controls-right">
          {/* Next Fault Button */}
          <button
            className="btn-next-fault"
            onClick={handleNextFault}
            disabled={allFaultyNodes.length === 0}
            title="Cycle through detected flaky tests and real bugs"
          >
            ⚡ Next fault ({allFaultyNodes.length})
          </button>
        </div>
      </div>

      {/* Tree Canvas */}
      <div className="tree-hierarchy-canvas" ref={treeContainerRef}>
        {loading ? (
          <div className="tree-loading-state">
            <div className="spinner"></div>
            <span>Building AST+Jedi knowledge tree from repository...</span>
          </div>
        ) : error ? (
          <div className="tree-error-state">{error}</div>
        ) : !treeRoot ? (
          <div className="tree-empty-state">No test cases found in current repository.</div>
        ) : (
          renderNode(treeRoot)
        )}
      </div>

      {/* Footer statistics strip */}
      {treeRoot && (
        <footer className="tree-stats-footer">
          <span className="footer-stat">
            <strong>{treeRoot.totalTests}</strong> total tests
          </span>
          <span className="footer-stat status-flaky">
            <strong>{treeRoot.flakyCount}</strong> flaky
          </span>
          <span className="footer-stat status-real">
            <strong>{treeRoot.bugCount}</strong> real bugs
          </span>
          <span className="footer-stat status-neutral">
            <strong>{treeRoot.totalTests - treeRoot.faultCount}</strong> passing
          </span>
          <span className="footer-hint">
            Click any test node to inspect AST evidence & citations
          </span>
        </footer>
      )}
    </div>
  );
};

