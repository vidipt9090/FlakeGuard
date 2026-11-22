import type { SharedState, TreeData, TreeNode } from '../types';

/** Fixed column geometry, copied from the approved Repo map design. */
export const COL = { repo: 24, file: 290, test: 570, state: 910 };
export const W = { repo: 170, file: 190, test: 230, state: 220 };
export const H = { repo: 56, file: 56, test: 64, state: 120 };
const PITCH = 88; // vertical distance between test rows
const TOP = 56;   // space for the column headings
const GAP = 16;   // extra space between files

export interface Placed { node: TreeNode; x: number; y: number; w: number; h: number; }
export interface Edge { d: string; id: string; }
export interface Arrow { d: string; id: string; kind: 'writes' | 'reads'; label: string; lx: number; ly: number; color: string; }
export interface PlacedState { state: SharedState; x: number; y: number; w: number; h: number; }
export interface TreeLayout {
  placed: Placed[]; edges: Edge[]; arrows: Arrow[]; states: PlacedState[]; width: number; height: number;
}
export interface LayoutOpts { faultsOnly: boolean; collapsed: Set<string>; }

const elbow = (x1: number, y1: number, x2: number, y2: number) => {
  const xm = Math.round((x1 + x2) / 2);
  return `M ${x1} ${y1} H ${xm} V ${y2} H ${x2}`;
};

export function layoutTree(data: TreeData, opts: LayoutOpts): TreeLayout {
  const placed: Placed[] = [];
  const edges: Edge[] = [];
  const testCenter = new Map<string, number>();

  let y = TOP;
  const fileCenters: { id: string; cy: number }[] = [];

  for (const file of data.root.children) {
    if (opts.faultsOnly && file.faults === 0) continue;
    const tests = file.children.filter((t) => !opts.faultsOnly || t.status !== 'clean');
    const folded = opts.collapsed.has(file.id);
    if (folded || tests.length === 0) {
      const cy = y + H.file / 2;
      placed.push({ node: file, x: COL.file, y: cy - H.file / 2, w: W.file, h: H.file });
      fileCenters.push({ id: file.id, cy });
      y += PITCH + GAP;
      continue;
    }
    const firstCy = y + H.test / 2;
    tests.forEach((t, i) => {
      const ty = y + i * PITCH;
      placed.push({ node: t, x: COL.test, y: ty, w: W.test, h: H.test });
      testCenter.set(t.id, ty + H.test / 2);
    });
    const lastCy = y + (tests.length - 1) * PITCH + H.test / 2;
    const fcy = Math.round((firstCy + lastCy) / 2);
    placed.push({ node: file, x: COL.file, y: fcy - H.file / 2, w: W.file, h: H.file });
    fileCenters.push({ id: file.id, cy: fcy });
    tests.forEach((t) => {
      const cy = testCenter.get(t.id)!;
      edges.push({ id: `${file.id}-${t.id}`, d: elbow(COL.file + W.file, fcy, COL.test, cy) });
    });
    y += tests.length * PITCH + GAP;
  }

  const rootCy = fileCenters.length
    ? Math.round((fileCenters[0].cy + fileCenters[fileCenters.length - 1].cy) / 2)
    : TOP + H.repo / 2;
  placed.push({ node: data.root, x: COL.repo, y: rootCy - H.repo / 2, w: W.repo, h: H.repo });
  fileCenters.forEach((f) => edges.push({ id: `root-${f.id}`, d: elbow(COL.repo + W.repo, rootCy, COL.file, f.cy) }));

  // Shared state nodes and the writes / reads arrows (only for tests that are visible).
  const arrows: Arrow[] = [];
  const states: PlacedState[] = [];
  for (const s of data.sharedState) {
    const wy = s.writers.map((id) => testCenter.get(id)).filter((v): v is number => v !== undefined);
    const ry = s.readers.map((id) => testCenter.get(id)).filter((v): v is number => v !== undefined);
    const all = [...wy, ...ry];
    if (all.length === 0) continue;
    // Fixed card height, centred on the readers (or on every linked test when there is no reader),
    // so a far-away writer never stretches the card. Its arrow bends instead.
    const anchor = ry.length ? ry : all;
    const mid = Math.round(anchor.reduce((a, b) => a + b, 0) / anchor.length);
    const top = Math.max(TOP, mid - H.state / 2);
    states.push({ state: s, x: COL.state, y: top, w: W.state, h: H.state });
    const onCard = (cy: number) => Math.min(Math.max(cy, top + 24), top + H.state - 24);
    const xm = Math.round((COL.test + W.test + COL.state) / 2);
    s.writers.forEach((id) => {
      const cy = testCenter.get(id);
      if (cy === undefined) return;
      const ey = onCard(cy);
      const d = ey === cy
        ? `M ${COL.test + W.test} ${cy} H ${COL.state - 4}`
        : `M ${COL.test + W.test} ${cy} H ${xm} V ${ey} H ${COL.state - 4}`;
      arrows.push({ id: `${s.id}-w-${id}`, kind: 'writes', label: 'writes', color: '#8F1D14',
        d, lx: COL.test + W.test + 30, ly: cy - 28 });
    });
    s.readers.forEach((id) => {
      const cy = testCenter.get(id);
      if (cy === undefined) return;
      const ey = onCard(cy);
      const d = ey === cy
        ? `M ${COL.state} ${cy} H ${COL.test + W.test + 4}`
        : `M ${COL.state} ${ey} H ${xm} V ${cy} H ${COL.test + W.test + 4}`;
      arrows.push({ id: `${s.id}-r-${id}`, kind: 'reads', label: 'reads', color: '#8A3A0B',
        d, lx: COL.test + W.test + 30, ly: cy + 12 });
    });
  }

  const bottom = Math.max(y, ...states.map((s) => s.y + s.h + GAP)) + 24;
  return { placed, edges, arrows, states, width: COL.state + W.state + 40, height: bottom };
}

/** Test nodes that carry a fault, in top-to-bottom order. Used by "Next fault". */
export function faultOrder(layout: TreeLayout): string[] {
  return layout.placed
    .filter((p) => p.node.kind === 'test' && p.node.status !== 'clean')
    .sort((a, b) => a.y - b.y)
    .map((p) => p.node.id);
}
