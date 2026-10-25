import { useEffect, useMemo, useRef } from "react";
import type { TraceEvent, TreeRow } from "./types";
import { EDGE_SHAPE, edgePath, layoutTree, revealOrder, type PlacedNode } from "./tree";
import { EDGE_HELP, depthColor } from "./ui";
import "./TreeCanvas.css";

/* The knowledge tree, drawn so that two things are readable at a glance:
 *
 *   horizontally — how many hops from the test a node is
 *   by colour    — which resolver found it: the AST walk, or jedi
 *
 * During a replay each node appears on the step that actually produced it
 * (the navigator records that; it is not inferred here), so you watch the
 * tree being built rather than watching a finished picture.
 */

const NODE_R = 7;
const ROW_H = 46;
const COL_W = 230;
const PAD_X = 34;
const PAD_Y = 30;
const LABEL_MAX = 30;

function shapePath(kind: string, r: number): string {
  switch (EDGE_SHAPE[kind] ?? "circle") {
    case "diamond":
      return `M 0 ${-r * 1.25} L ${r * 1.15} 0 L 0 ${r * 1.25} L ${-r * 1.15} 0 Z`;
    case "square":
      return `M ${-r * 0.92} ${-r * 0.92} H ${r * 0.92} V ${r * 0.92} H ${-r * 0.92} Z`;
    case "triangle":
      return `M ${-r} ${-r * 1.05} L ${r * 1.2} 0 L ${-r} ${r * 1.05} Z`;
    case "hex": {
      const pts = Array.from({ length: 6 }, (_, i) => {
        const a = (Math.PI / 3) * i - Math.PI / 6;
        return `${(Math.cos(a) * r * 1.1).toFixed(2)} ${(Math.sin(a) * r * 1.1).toFixed(2)}`;
      });
      return `M ${pts.join(" L ")} Z`;
    }
    case "cross": {
      const t = r * 0.42;
      const l = r * 1.15;
      return `M ${-t} ${-l} H ${t} V ${-t} H ${l} V ${t} H ${t} V ${l} H ${-t} V ${t} H ${-l} V ${-t} H ${-t} Z`;
    }
    case "star": {
      const pts: string[] = [];
      for (let i = 0; i < 10; i++) {
        const rad = i % 2 === 0 ? r * 1.45 : r * 0.62;
        const a = (Math.PI / 5) * i - Math.PI / 2;
        pts.push(`${(Math.cos(a) * rad).toFixed(2)} ${(Math.sin(a) * rad).toFixed(2)}`);
      }
      return `M ${pts.join(" L ")} Z`;
    }
    default:
      return "";
  }
}

function truncate(text: string): string {
  return text.length > LABEL_MAX ? `${text.slice(0, LABEL_MAX - 1)}…` : text;
}

/** The root is a full pytest node id, which is far too long to sit beside
 *  its siblings. Show the test name; the file is on the sublabel. */
function rootLabels(testId: string): [string, string] {
  const [file, ...rest] = testId.split("::");
  return [rest.join("::") || file, file.split("/").slice(-2).join("/")];
}

export function TreeCanvas({
  rows,
  events,
  step,
  selectedId,
  onSelect,
  maxDepthShown,
}: {
  rows: TreeRow[];
  events: TraceEvent[];
  /** Replay position. Pass Infinity for the finished tree. */
  step: number;
  selectedId?: string | null;
  onSelect?: (node: PlacedNode | null) => void;
  maxDepthShown?: number;
}) {
  const layout = useMemo(() => {
    const limit = maxDepthShown ?? Infinity;
    const kept = rows.filter((r) => r.depth <= limit);
    return layoutTree(kept, revealOrder(events));
  }, [rows, events, maxDepthShown]);

  // A wide tree opens scrolled to wherever the browser left it, which on a
  // 40-node tree is usually empty space. Put the root in view instead.
  const scrollRef = useRef<HTMLDivElement>(null);
  const rootNode = layout.nodes.find((n) => n.depth === 0);
  useEffect(() => {
    const box = scrollRef.current;
    if (!box || !rootNode) return;
    const y = PAD_Y + rootNode.y * ROW_H + ROW_H / 2;
    box.scrollTop = Math.max(0, y - box.clientHeight / 2);
    box.scrollLeft = 0;
  }, [rootNode?.id, rootNode?.y]);

  const width = PAD_X * 2 + (layout.maxDepth + 1) * COL_W;
  const height = PAD_Y * 2 + layout.rows * ROW_H;

  const scoreMax = Math.max(1, ...layout.nodes.map((n) => n.score));
  const px = (n: PlacedNode) => PAD_X + n.x * COL_W;
  const py = (n: PlacedNode) => PAD_Y + n.y * ROW_H + ROW_H / 2;

  const visible = (n: PlacedNode) => n.depth === 0 || n.bornAt <= step;
  const justBorn = (n: PlacedNode) => n.bornAt === step && n.depth > 0;

  if (!layout.nodes.length) {
    return <div className="tree-empty">Nothing to draw.</div>;
  }

  return (
    <div className="tree-canvas" ref={scrollRef}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        role="img"
        aria-label="Knowledge tree: hop depth left to right"
      >
        {/* depth columns, so the x axis reads without a ruler */}
        {Array.from({ length: layout.maxDepth + 1 }, (_, d) => (
          <g key={`col-${d}`} className="tree-col">
            <line
              x1={PAD_X + d * COL_W}
              y1={6}
              x2={PAD_X + d * COL_W}
              y2={height - 20}
              className="tree-col-line"
            />
            <text x={PAD_X + d * COL_W} y={height - 6} className="tree-col-label">
              {d === 0 ? "the test" : `hop ${d}`}
            </text>
          </g>
        ))}

        {/* edges first, so markers sit on top of them */}
        <g>
          {layout.edges.map((e, i) => {
            const on = visible(e.to);
            return (
              <path
                key={`e-${i}`}
                d={edgePath(px(e.from), py(e.from), px(e.to), py(e.to))}
                className={`tree-edge ${on ? "is-on" : "is-off"} ${
                  justBorn(e.to) ? "is-new" : ""
                }`}
                fill="none"
              />
            );
          })}
        </g>

        {/* nodes */}
        <g>
          {layout.nodes.map((n) => {
            const on = visible(n);
            const hue =
              n.depth === 0
                ? "var(--accent)"
                : n.via === "jedi"
                  ? "var(--jedi)"
                  : "var(--ast)";
            const r = NODE_R + 5 * Math.sqrt(Math.max(0, n.score) / scoreMax);
            const shape = shapePath(n.depth === 0 ? "root" : n.edge, r);
            const selected = selectedId === n.id;
            const x = px(n);
            const y = py(n);
            return (
              <g
                key={n.id}
                className={`tree-node ${on ? "is-on" : "is-off"} ${
                  justBorn(n) ? "is-new" : ""
                } ${selected ? "is-selected" : ""}`}
                transform={`translate(${x} ${y})`}
                onClick={() => onSelect?.(selected ? null : n)}
                tabIndex={on ? 0 : -1}
                role="button"
                aria-label={`${n.label}, ${n.edge}, hop ${n.depth}`}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter" || ev.key === " ") {
                    ev.preventDefault();
                    onSelect?.(selected ? null : n);
                  }
                }}
              >
                <title>
                  {`${n.label}\nhop ${n.depth} · ${n.edge} · score ${n.score}\n` +
                    `${n.path ? `${n.path}:${n.start_line}` : ""}\n` +
                    `${EDGE_HELP[n.edge] ?? ""}`}
                </title>
                {selected ? <circle r={r + 9} className="tree-halo" /> : null}
                {justBorn(n) ? <circle r={r} className="tree-pulse" style={{ stroke: hue }} /> : null}
                {shape ? (
                  <path d={shape} fill={hue} className="tree-marker" />
                ) : (
                  <circle r={r} fill={hue} className="tree-marker" />
                )}
                <text x={r + 9} y={n.depth === 0 ? -1 : 4} className="tree-label">
                  {n.depth === 0 ? truncate(rootLabels(n.label)[0]) : truncate(n.label)}
                </text>
                {n.depth === 0 ? (
                  <text x={r + 9} y={12} className="tree-sublabel">
                    {rootLabels(n.label)[1]}
                  </text>
                ) : n.score > 0 ? (
                  <text x={r + 9} y={17} className="tree-sublabel">
                    {n.edge} · {n.score}
                  </text>
                ) : null}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

/** Small key for the depth ramp, shown beside the canvas. */
export function DepthKey({ maxDepth }: { maxDepth: number }) {
  if (maxDepth <= 0) return null;
  return (
    <div className="depth-key">
      <span className="depth-key-label">hop</span>
      {Array.from({ length: maxDepth + 1 }, (_, d) => (
        <span key={d} className="depth-key-step">
          <i style={{ background: depthColor(d, maxDepth) }} />
          {d}
        </span>
      ))}
    </div>
  );
}
