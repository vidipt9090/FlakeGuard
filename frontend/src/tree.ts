import type { Explain, TraceEvent, TreeRow } from "./types";

/* Layout and replay maths for the knowledge tree.
 *
 * Kept out of the component so it can be reasoned about (and read) without
 * JSX in the way. Two jobs:
 *
 *   layoutTree  -- place every node: x is hop depth, y is a tidy-tree slot
 *   revealOrder -- say which trace step first produced each node, so the
 *                  replay can grow the tree exactly in step with the trace
 */

export interface PlacedNode extends TreeRow {
  x: number;
  y: number;
  /** Trace step that first produced this node; 0 for the root. */
  bornAt: number;
}

export interface PlacedEdge {
  from: PlacedNode;
  to: PlacedNode;
  bornAt: number;
}

export interface Layout {
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  maxDepth: number;
  rows: number;
}

/** Row height in abstract units; the component scales to pixels. */
const ROW = 1;

/**
 * Place nodes with depth on x and a tidy-tree slot on y.
 *
 * Leaves take the next free slot in display order; a parent is centred on
 * its children. That is the standard tidy placement and it is what stops
 * edges from crossing, which matters here because the edges *are* the
 * explanation.
 */
export function layoutTree(rows: TreeRow[], bornAt: Map<string, number>): Layout {
  const byId = new Map<string, PlacedNode>();
  for (const row of rows) {
    byId.set(row.id, { ...row, x: row.depth, y: 0, bornAt: bornAt.get(keyOf(row)) ?? 0 });
  }

  const children = new Map<string, string[]>();
  const roots: string[] = [];
  for (const row of rows) {
    children.set(row.id, children.get(row.id) ?? []);
  }
  for (const row of rows) {
    if (row.parent && byId.has(row.parent)) {
      children.get(row.parent)!.push(row.id);
    } else {
      roots.push(row.id);
    }
  }

  // Order siblings nearest-edge first so the picture reads top-to-bottom in
  // the same order as the text tree.
  const edgeRank: Record<string, number> = {
    calls: 0,
    infers: 1,
    overrides: 2,
    fixture: 3,
    "fixture-builds": 4,
    expands: 5,
    touches: 6,
    smells: 7,
  };
  for (const list of children.values()) {
    list.sort((a, b) => {
      const na = byId.get(a)!;
      const nb = byId.get(b)!;
      const ra = edgeRank[na.edge] ?? 99;
      const rb = edgeRank[nb.edge] ?? 99;
      if (ra !== rb) return ra - rb;
      if (nb.score !== na.score) return nb.score - na.score;
      return na.label.localeCompare(nb.label);
    });
  }

  let cursor = 0;
  const place = (id: string): number => {
    const kids = children.get(id) ?? [];
    const node = byId.get(id)!;
    if (kids.length === 0) {
      node.y = cursor;
      cursor += ROW;
      return node.y;
    }
    const ys = kids.map(place);
    node.y = (Math.min(...ys) + Math.max(...ys)) / 2;
    return node.y;
  };
  roots.forEach(place);

  const nodes = [...byId.values()];
  const edges: PlacedEdge[] = [];
  for (const row of rows) {
    if (row.parent && byId.has(row.parent)) {
      const to = byId.get(row.id)!;
      edges.push({ from: byId.get(row.parent)!, to, bornAt: to.bornAt });
    }
  }

  return {
    nodes,
    edges,
    maxDepth: nodes.reduce((m, n) => Math.max(m, n.depth), 0),
    rows: Math.max(1, cursor),
  };
}

/** How a trace step names a node it produced. Mirrors ast_nav.py. */
export function keyOf(row: { kind: string; label: string; path: string; start_line: number }): string {
  return row.kind === "smell" ? `smell:${row.label}` : `${row.path}:${row.start_line}`;
}

/**
 * First step that produced each node.
 *
 * The navigator records this per step rather than it being inferred here —
 * a guess would put nodes on screen at the wrong moment and quietly
 * misrepresent how the search works.
 */
export function revealOrder(events: TraceEvent[]): Map<string, number> {
  const first = new Map<string, number>();
  for (const event of events) {
    for (const key of event.produced ?? []) {
      if (!first.has(key)) first.set(key, event.seq);
    }
  }
  return first;
}

/** Nodes visible at a given step of the replay. */
export function visibleAt(layout: Layout, step: number): Set<string> {
  const out = new Set<string>();
  for (const node of layout.nodes) {
    if (node.depth === 0 || node.bornAt <= step) out.add(node.id);
  }
  return out;
}

/** Which test-source lines the AST walk has read by a given step. */
export function readLines(events: TraceEvent[], step: number, path: string): Set<number> {
  const out = new Set<number>();
  for (const event of events) {
    if (event.seq > step) break;
    if (event.phase === "ast_walk" && event.path === path && event.line) {
      out.add(event.line);
    }
  }
  return out;
}

/** Phases present in this trace, in the order the navigator runs them. */
export function phasesIn(events: TraceEvent[], order: string[]): string[] {
  const present = new Set(events.map((e) => e.phase));
  return order.filter((p) => present.has(p));
}

/** A cubic path from parent to child that leaves and arrives horizontally. */
export function edgePath(x1: number, y1: number, x2: number, y2: number): string {
  const mid = x1 + (x2 - x1) * 0.5;
  return `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
}

/** Marker shape per edge type, so identity survives greyscale. */
export const EDGE_SHAPE: Record<string, "circle" | "diamond" | "square" | "triangle" | "hex" | "cross" | "star"> = {
  root: "star",
  calls: "circle",
  infers: "diamond",
  fixture: "square",
  "fixture-builds": "square",
  overrides: "triangle",
  expands: "triangle",
  touches: "hex",
  smells: "cross",
  reaches: "circle",
};

/** Summary counts the header strip shows for whichever explain is loaded. */
export function headline(explain: Explain) {
  const stats = explain.tree.stats;
  const trace = explain.trace.summary;
  return {
    nodes: stats.nodes,
    depth: stats.max_depth,
    files: stats.files_touched,
    astNames: trace.ast_names,
    gotoCalls: trace.jedi_goto_calls,
    inferCalls: trace.jedi_infer_calls,
    hitRate: trace.jedi_hit_rate,
    steps: trace.events,
    ms: explain.elapsed_ms ?? trace.total_ms,
  };
}
