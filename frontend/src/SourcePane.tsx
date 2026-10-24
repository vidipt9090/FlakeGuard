import { useEffect, useMemo, useRef } from "react";
import type { TraceEvent } from "./types";
import "./SourcePane.css";

/* The test's own source, with the line the AST walk is currently reading
 * highlighted and every line it has already read marked.
 *
 * This is the half of the story a tree alone cannot tell: the walk is pure
 * syntax over this text, and it is what decides the work list jedi is then
 * handed. Watching the highlight move down the test while nodes appear on
 * the right is the whole mechanism in one view.
 */

export function SourcePane({
  source,
  events,
  step,
}: {
  source: { path: string; start_line: number; end_line: number; text: string } | null;
  events: TraceEvent[];
  step: number;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);

  const { lines, read, current, names } = useMemo(() => {
    const text = source?.text ?? "";
    const startLine = source?.start_line ?? 1;
    const path = source?.path ?? "";

    const readSet = new Set<number>();
    const nameAt = new Map<number, string[]>();
    let currentLine: number | null = null;

    for (const event of events) {
      if (event.seq > step) break;
      const onThisFile = !event.path || event.path === path;
      if (!onThisFile || !event.line) continue;
      if (event.phase === "ast_walk") {
        readSet.add(event.line);
        const list = nameAt.get(event.line) ?? [];
        if (!list.includes(event.label)) list.push(event.label);
        nameAt.set(event.line, list);
      }
      if (
        event.seq === step &&
        (event.phase === "ast_walk" || event.phase.startsWith("jedi"))
      ) {
        currentLine = event.line;
      }
    }

    return {
      lines: text.split("\n").map((content, i) => ({ n: startLine + i, content })),
      read: readSet,
      current: currentLine,
      names: nameAt,
    };
  }, [source, events, step]);

  // Keep the active line in view as the replay runs.
  useEffect(() => {
    if (current === null || !bodyRef.current) return;
    const el = bodyRef.current.querySelector<HTMLElement>(`[data-line="${current}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [current]);

  if (!source) {
    return (
      <div className="source-pane">
        <div className="source-head">
          <span className="source-path">no source</span>
        </div>
        <div className="source-missing">
          This export was written without the test's source. Re-run
          <code>scripts/export_knowledge_trees.py --with-text</code>, or use a live run.
        </div>
      </div>
    );
  }

  return (
    <div className="source-pane">
      <div className="source-head">
        <span className="source-path" title={source.path}>
          {source.path}
        </span>
        <span className="source-range">
          L{source.start_line}–{source.end_line}
        </span>
      </div>
      <div className="source-body" ref={bodyRef}>
        <pre>
          {lines.map((line) => {
            const isRead = read.has(line.n);
            const isCurrent = current === line.n;
            const found = names.get(line.n);
            return (
              <div
                key={line.n}
                data-line={line.n}
                className={`src-line ${isRead ? "is-read" : ""} ${isCurrent ? "is-current" : ""}`}
                title={line.content}
              >
                <span className="src-num">{line.n}</span>
                <code className="src-text">{line.content || " "}</code>
                {isRead && found?.length ? (
                  <span className="src-names" title={`names collected here: ${found.join(", ")}`}>
                    {found.slice(0, 3).join(" ")}
                    {found.length > 3 ? ` +${found.length - 3}` : ""}
                  </span>
                ) : null}
              </div>
            );
          })}
        </pre>
      </div>
      <div className="source-foot">
        <span className="src-key">
          <i className="src-key-read" /> read by the AST walk
        </span>
        <span className="src-key">
          <i className="src-key-now" /> current step
        </span>
      </div>
    </div>
  );
}
