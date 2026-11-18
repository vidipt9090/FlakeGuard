import { useMemo } from 'react';
import type { TreeData, TreeNode } from '../types';
import { STATUS_ICON } from './Icons';
import { COL, faultOrder, layoutTree, type TreeLayout } from './treeLayout';

interface Props {
  data: TreeData;
  selectedId: string | null;
  query: string;
  faultsOnly: boolean;
  collapsed: Set<string>;
  onSelect: (node: TreeNode) => void;
  onToggleFile: (fileId: string) => void;
}

export function useTreeLayout(data: TreeData, faultsOnly: boolean, collapsed: Set<string>): TreeLayout {
  return useMemo(() => layoutTree(data, { faultsOnly, collapsed }), [data, faultsOnly, collapsed]);
}
export { faultOrder };

export function RepoTree({ data, selectedId, query, faultsOnly, collapsed, onSelect, onToggleFile }: Props) {
  const layout = useTreeLayout(data, faultsOnly, collapsed);
  const q = query.trim().toLowerCase();
  const matches = (n: TreeNode) => !q || n.name.toLowerCase().includes(q);

  return (
    <div className="tree-scroll">
      <div className="tree-host" style={{ width: layout.width, height: layout.height }}>
        {[['Repository', COL.repo], ['Files', COL.file], ['Tests', COL.test], ['Shared state', COL.state]].map(([t, x]) => (
          <div key={t as string} className="tree-col" style={{ left: x as number }}>{t}</div>
        ))}

        {/* lines and arrows first, so cards paint on top */}
        <svg className="tree-svg" width={layout.width} height={layout.height} aria-hidden="true">
          <defs>
            <marker id="ah-w" orient="auto" markerWidth="6" markerHeight="6" refX="4" refY="3"><path d="M0 0 L6 3 L0 6 Z" fill="#8F1D14" /></marker>
            <marker id="ah-r" orient="auto" markerWidth="6" markerHeight="6" refX="4" refY="3"><path d="M0 0 L6 3 L0 6 Z" fill="#8A3A0B" /></marker>
          </defs>
          {layout.edges.map((e) => (
            <path key={e.id} d={e.d} fill="none" stroke="#7A7F88" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          ))}
          {layout.arrows.map((a) => (
            <path key={a.id} d={a.d} fill="none" stroke={a.color} strokeWidth="2" strokeLinecap="round"
              markerEnd={`url(#${a.kind === 'writes' ? 'ah-w' : 'ah-r'})`} />
          ))}
        </svg>

        {layout.states.map(({ state, x, y, w, h }) => (
          <div key={state.id} className="tcard state" style={{ left: x, top: y, width: w, height: h }}>
            <span>
              <span className="nm" style={{ fontSize: 15 }}>{state.name}</span>
              <span className="st mono" style={{ fontSize: 12, color: 'var(--muted)' }}>{state.path}</span>
              <span className="st">{state.note}</span>
            </span>
          </div>
        ))}

        {layout.placed.map(({ node, x, y, w, h }) => {
          const isTest = node.kind === 'test';
          const cls = node.kind === 'repo' ? 'repo' : node.kind === 'file' ? 'file' : node.status;
          const Icon = isTest ? STATUS_ICON[node.status] : null;
          const dim = !matches(node) ? 'dim' : '';
          const sel = node.id === selectedId ? 'selected' : '';
          const inner = (
            <>
              {Icon && <Icon />}
              <span>
                <span className="nm">{node.name}</span>
                <span className="st">{node.label}</span>
              </span>
            </>
          );
          const style = { left: x, top: y, width: w, height: h };
          if (node.kind === 'repo') return <div key={node.id} className={`tcard ${cls}`} style={style}>{inner}</div>;
          return (
            <button key={node.id} type="button" className={`tcard ${cls} ${dim} ${sel}`} style={style}
              aria-pressed={node.id === selectedId}
              aria-label={`${node.name}. ${node.label}`}
              onClick={() => (node.kind === 'file' ? onToggleFile(node.id) : onSelect(node))}>
              {inner}
            </button>
          );
        })}

        {layout.arrows.map((a) => (
          <span key={`${a.id}-l`} className="tree-lab" style={{ left: a.lx - 30, top: a.ly, color: a.color }}>{a.label}</span>
        ))}
      </div>
    </div>
  );
}
