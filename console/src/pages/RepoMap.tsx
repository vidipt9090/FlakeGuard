import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { Header } from '../components/Header';
import { RunNotice } from '../components/RunNotice';
import { RepoTree, faultOrder, useTreeLayout } from '../components/RepoTree';
import { VerdictChip } from '../components/StatusChip';
import { usePolling } from '../hooks/usePolling';
import { useRun } from '../RunContext';
import type { TreeData, TreeNode } from '../types';

export default function RepoMap() {
  const { runId } = useRun();
  const rid = runId ?? 'none';
  const { data } = usePolling(() => api.getTree(rid), 6000, true, [rid]);
  const [query, setQuery] = useState('');
  const [faultsOnly, setFaultsOnly] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const layout = useTreeLayout(data ?? EMPTY, faultsOnly, collapsed);
  const faults = useMemo(() => faultOrder(layout), [layout]);

  // Select the first fault on load so the blue ring and the Selected panel are never empty.
  useEffect(() => {
    if (selectedId === null && faults.length > 0) setSelectedId(faults[0]);
  }, [faults, selectedId]);

  const selected = useMemo(() => {
    const find = (n: TreeNode): TreeNode | null => (n.id === selectedId ? n : n.children.map(find).find(Boolean) ?? null);
    return data && selectedId ? find(data.root) : null;
  }, [data, selectedId]);

  function nextFault() {
    if (faults.length === 0) return;
    const i = faults.indexOf(selectedId ?? '');
    setSelectedId(faults[(i + 1) % faults.length]);
  }
  function toggleFile(id: string) {
    setCollapsed((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }
  const allFiles = data?.root.children.map((f) => f.id) ?? [];

  return (
    <>
      <Header />
      <main className="main">
        <RunNotice runId={runId} />
        <div>
          <h1>Repo map</h1>
          <p className="lead">The repository drawn as a tree, built from the code itself. Faults stand out, and the shared value that links two tests is drawn in.</p>
        </div>

        <section className="card tight form" aria-label="Tree controls">
          <div className="field" style={{ flex: '1 1 260px' }}>
            <label htmlFor="find">Find a test or file</label>
            <input id="find" className="input" placeholder="for example test_report" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <label className="check"><input type="checkbox" checked={faultsOnly} onChange={(e) => setFaultsOnly(e.target.checked)} /> Show faults only</label>
          <button type="button" className="btn" onClick={nextFault}>Next fault</button>
          <button type="button" className="btn" onClick={() => setCollapsed(collapsed.size ? new Set() : new Set(allFiles))}>
            {collapsed.size ? 'Expand all' : 'Collapse all'}
          </button>
        </section>

        <section className="card" aria-label="Test tree" style={{ padding: 16 }}>
          {data
            ? <RepoTree data={data} selectedId={selectedId} query={query} faultsOnly={faultsOnly} collapsed={collapsed}
                onSelect={(n) => setSelectedId(n.id)} onToggleFile={toggleFile} />
            : <p>Loading the tree…</p>}
        </section>

        <div className="row">
          <section className="card grow" aria-label="Selected test">
            <div className="eyebrow">Selected: ringed in blue</div>
            {selected ? (
              <>
                <h2 className="mono" style={{ margin: '6px 0 4px', wordBreak: 'break-all' }}>{selected.name}</h2>
                {selected.path && <div className="mono footnote">{selected.path}</div>}
                <p style={{ margin: '10px 0' }}>
                  {selected.status !== 'clean' && selected.status !== 'polluter'
                    ? <VerdictChip verdict={selected.status} /> : <span className="chip">{selected.label}</span>}
                </p>
                {selected.findingId && <p><Link to="/findings" style={{ fontWeight: 600 }}>Open the full finding →</Link></p>}
              </>
            ) : <p className="lead" style={{ marginTop: 8 }}>Click a test to see what is known about it.</p>}
          </section>
          <section className="card grow" aria-label="How to read the tree">
            <h2 style={{ fontSize: 15 }}>How to read this</h2>
            <ul style={{ margin: '8px 0 0', paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <li>Read left to right: repository, file, test.</li>
              <li>A thick outline and a label mark a fault. Clean tests stay flat and quiet.</li>
              <li>An arrow into a shared value means a test writes it. An arrow out means a test reads it.</li>
              <li>Click a test to see its finding. Click a file to fold its tests away.</li>
            </ul>
          </section>
        </div>
      </main>
    </>
  );
}

const EMPTY: TreeData = { root: { id: 'repo', kind: 'repo', name: '', path: null, status: 'clean', label: '', faults: 0, findingId: null, children: [] }, sharedState: [] };
