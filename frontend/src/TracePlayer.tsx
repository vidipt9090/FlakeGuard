import { useEffect, useMemo, useRef } from "react";
import type { TraceEvent } from "./types";
import { phasesIn } from "./tree";
import { PHASE_HELP, PHASE_ORDER, depthColor, ms } from "./ui";
import "./TracePlayer.css";

/* Transport for the replay, plus the raster that shows where you are.
 *
 * Phase identity is carried by the ROW a mark sits on, never by hue: there
 * are up to ten phases and nobody can separate ten colours. Colour is spent
 * on hop depth instead, which is a magnitude and takes a single-hue ramp.
 */

export function TracePlayer({
  events,
  step,
  playing,
  speed,
  onStep,
  onPlayPause,
  onSpeed,
}: {
  events: TraceEvent[];
  step: number;
  playing: boolean;
  speed: number;
  onStep: (s: number) => void;
  onPlayPause: () => void;
  onSpeed: (s: number) => void;
}) {
  const total = events.length;
  const current = events[Math.max(0, Math.min(total - 1, step - 1))];
  const phases = useMemo(() => phasesIn(events, PHASE_ORDER), [events]);
  const maxDepth = useMemo(() => events.reduce((m, e) => Math.max(m, e.depth), 0), [events]);
  const maxMs = useMemo(() => events.reduce((m, e) => Math.max(m, e.duration_ms), 0), [events]);

  // Steps that actually put something on the tree. On cachetools only 18 of
  // 470 do, so scrubbing blind mostly lands on nothing happening.
  const discoveries = useMemo(
    () => events.filter((e) => e.produced?.length).map((e) => e.seq),
    [events],
  );
  const nextDiscovery = discoveries.find((s) => s > step);
  const prevDiscovery = [...discoveries].reverse().find((s) => s < step);

  // Advance the replay. Steps that did nothing interesting are skipped over
  // quickly so a 468-step trace stays watchable.
  const tick = useRef<number | null>(null);
  useEffect(() => {
    if (!playing) return;
    const delay = Math.max(16, 420 / speed);
    tick.current = window.setInterval(() => {
      onStep(step >= total ? total : step + 1);
    }, delay);
    return () => {
      if (tick.current) window.clearInterval(tick.current);
    };
  }, [playing, speed, step, total, onStep]);

  // Keyboard transport: space toggles, arrows step, home/end jump.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === " ") {
        e.preventDefault();
        onPlayPause();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        onStep(Math.min(total, step + (e.shiftKey ? 10 : 1)));
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        onStep(Math.max(1, step - (e.shiftKey ? 10 : 1)));
      } else if (e.key === "Home") {
        onStep(1);
      } else if (e.key === "End") {
        onStep(total);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, total, onStep, onPlayPause]);

  if (!total) return null;

  // Position as a percentage of the lane, so marks stay round at any width.
  const pos = (seq: number) => ((seq - 1) / Math.max(1, total - 1)) * 100;

  return (
    <div className="player">
      <div className="player-bar">
        <div className="player-transport">
          <button
            className="pbtn pbtn-primary"
            onClick={onPlayPause}
            title={playing ? "Pause (space)" : "Play the navigation (space)"}
            aria-label={playing ? "Pause" : "Play"}
          >
            {playing ? (
              <svg width="12" height="13" viewBox="0 0 12 13" aria-hidden>
                <rect x="1" y="1" width="3.5" height="11" rx="1" fill="currentColor" />
                <rect x="7.5" y="1" width="3.5" height="11" rx="1" fill="currentColor" />
              </svg>
            ) : (
              <svg width="12" height="13" viewBox="0 0 12 13" aria-hidden>
                <path d="M1.5 1.2 L11 6.5 L1.5 11.8 Z" fill="currentColor" />
              </svg>
            )}
          </button>
          <button className="pbtn" onClick={() => onStep(1)} title="Back to the start (Home)">
            ⏮
          </button>
          <button
            className="pbtn"
            onClick={() => onStep(Math.max(1, step - 1))}
            title="Previous step (←)"
          >
            ◀
          </button>
          <button
            className="pbtn"
            onClick={() => onStep(Math.min(total, step + 1))}
            title="Next step (→)"
          >
            ▶
          </button>
          <button className="pbtn" onClick={() => onStep(total)} title="Jump to the end (End)">
            ⏭
          </button>
          <span className="pbtn-sep" />
          <button
            className="pbtn"
            onClick={() => prevDiscovery && onStep(prevDiscovery)}
            disabled={!prevDiscovery}
            title="Previous step that added a node to the tree"
          >
            ◀◆
          </button>
          <button
            className="pbtn"
            onClick={() => nextDiscovery && onStep(nextDiscovery)}
            disabled={!nextDiscovery}
            title={`Next step that adds a node (${discoveries.length} of ${total} steps do)`}
          >
            ◆▶
          </button>
        </div>

        <div className="player-scrub-wrap">
          <div className="player-ticks" aria-hidden>
            {discoveries.map((seq) => (
              <i key={seq} style={{ left: `${pos(seq)}%` }} title={`step ${seq} adds a node`} />
            ))}
          </div>
          <input
          className="player-scrub"
          type="range"
          min={1}
          max={total}
          value={step}
          onChange={(e) => onStep(Number(e.target.value))}
          aria-label="Navigation step"
          />
        </div>

        <div className="player-right">
          <span className="player-count mono">
            {step} / {total}
          </span>
          <div className="player-speeds">
            {[1, 2, 4, 8].map((s) => (
              <button
                key={s}
                className={`pbtn pbtn-sm ${speed === s ? "is-active" : ""}`}
                onClick={() => onSpeed(s)}
                title={`${s}× speed`}
              >
                {s}×
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="raster-wrap">
        <div className="raster-grid">
          {phases.map((phase) => (
            <div key={phase} className="raster-row">
              <span className="raster-label" title={PHASE_HELP[phase]}>
                {phase}
              </span>
              <div className="raster-lane">
                {events
                  .filter((e) => e.phase === phase)
                  .map((e) => {
                    const done = e.seq <= step;
                    const size = 6 + Math.min(9, (e.duration_ms / Math.max(1, maxMs)) * 9);
                    return (
                      <button
                        key={e.seq}
                        type="button"
                        className={`raster-dot ${done ? "is-done" : "is-todo"} ${e.ok ? "" : "is-bad"} ${
                          e.seq === step ? "is-current" : ""
                        }`}
                        style={{
                          left: `${pos(e.seq)}%`,
                          width: size,
                          height: size,
                          background: done ? depthColor(e.depth, maxDepth) : "transparent",
                        }}
                        onClick={() => onStep(e.seq)}
                        title={`step ${e.seq} · ${e.phase}/${e.op}
${e.label}
hop ${e.depth} · returned ${e.results}, kept ${e.kept} · ${ms(e.duration_ms)}`}
                        aria-label={`step ${e.seq}, ${e.phase}`}
                      />
                    );
                  })}
              </div>
            </div>
          ))}
          <div className="raster-overlay">
            <div className="raster-cursor" style={{ left: `${pos(step)}%` }} />
          </div>
        </div>
      </div>

      {current ? <StepCard event={current} total={total} /> : null}
    </div>
  );
}

function StepCard({ event, total }: { event: TraceEvent; total: number }) {
  const tone = !event.ok ? "bad" : event.phase.startsWith("jedi") ? "jedi" : "ast";
  return (
    <div className={`stepcard tone-border-${tone}`}>
      <div className="stepcard-head">
        <span className="stepcard-seq mono">
          step {event.seq}/{total}
        </span>
        <span className={`stepcard-phase tone-${tone}`}>
          {event.phase} / {event.op}
        </span>
        <span className="stepcard-meta">hop {event.depth}</span>
        <span className="stepcard-meta">via {event.via}</span>
        <span className="stepcard-meta">{ms(event.duration_ms)}</span>
        {!event.ok ? <span className="stepcard-meta tone-bad">failed</span> : null}
      </div>
      <div className="stepcard-label mono">{event.label}</div>
      <div className="stepcard-rows">
        <div>
          <b>What this phase does</b>
          <span>{PHASE_HELP[event.phase] ?? "—"}</span>
        </div>
        <div>
          <b>This step</b>
          <span>{event.detail || "—"}</span>
        </div>
        <div>
          <b>Outcome</b>
          <span>
            {event.phase.startsWith("jedi")
              ? `jedi returned ${event.results}, ${event.kept} survived filtering`
              : `${event.results} item(s)`}
            {event.produced?.length
              ? ` · added ${event.produced.length} node${event.produced.length > 1 ? "s" : ""} to the tree`
              : ""}
            {event.path ? ` · ${event.path}${event.line ? `:${event.line}` : ""}` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}
