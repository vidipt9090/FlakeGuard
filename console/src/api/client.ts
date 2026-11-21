import type {
  AskAnswer, Finding, LabelType, NoTestsPlan, ResultsData, RunStatus, StartRunRequest, TreeData,
} from '../types';
import {
  MOCK_FINDINGS, MOCK_NOTESTS, MOCK_RESULTS, MOCK_TREE, mockAsk, mockRun, mockStart,
} from './mock';

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === '1';
const BASE: string = import.meta.env.VITE_API_BASE ?? '';

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json())?.detail ?? ''; } catch { /* ignore */ }
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ''}`);
  }
  return res.json() as Promise<T>;
}
const post = <T,>(path: string, body?: unknown) =>
  http<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

const wait = <T,>(v: T) => new Promise<T>((r) => setTimeout(() => r(v), 150));

export interface Health { ok: boolean; mode: string; docker: boolean; recorded: string | null }

export const api = {
  health: (): Promise<Health> =>
    USE_MOCK ? wait({ ok: true, mode: 'local', docker: false, recorded: null }) : http('/api/health'),

  startRun: (req: StartRunRequest): Promise<{ id: string }> =>
    USE_MOCK ? wait(mockStart(req)) : post('/api/runs', req),

  getRun: (id: string): Promise<RunStatus> =>
    USE_MOCK ? wait(mockRun()) : http(`/api/runs/${encodeURIComponent(id)}`),

  getFindings: (runId: string): Promise<Finding[]> =>
    USE_MOCK ? wait(MOCK_FINDINGS) : http(`/api/runs/${encodeURIComponent(runId)}/findings`),

  getTree: (runId: string): Promise<TreeData> =>
    USE_MOCK ? wait(MOCK_TREE) : http(`/api/runs/${encodeURIComponent(runId)}/tree`),

  getNoTests: (runId: string): Promise<NoTestsPlan> =>
    USE_MOCK ? wait(MOCK_NOTESTS) : http(`/api/runs/${encodeURIComponent(runId)}/no-tests`),

  ask: (findingId: string, question: string): Promise<AskAnswer> =>
    USE_MOCK ? wait(mockAsk(question)) : post(`/api/findings/${encodeURIComponent(findingId)}/ask`, { question }),

  proposeFix: (findingId: string): Promise<{ prUrl: string }> =>
    USE_MOCK ? wait({ prUrl: '#' }) : post(`/api/findings/${encodeURIComponent(findingId)}/fix`),

  reverify: (findingId: string, runs = 5): Promise<{ started: boolean }> =>
    USE_MOCK ? wait({ started: true }) : post(`/api/findings/${encodeURIComponent(findingId)}/reverify`, { runs }),

  quarantine: (findingId: string): Promise<{ issueUrl: string }> =>
    USE_MOCK ? wait({ issueUrl: '#' }) : post(`/api/findings/${encodeURIComponent(findingId)}/quarantine`),

  getResults: (label: LabelType): Promise<ResultsData> =>
    USE_MOCK ? wait(MOCK_RESULTS) : http(`/api/results?label=${label}`),
};
