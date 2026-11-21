import { api } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { Banner } from './Banner';

/** Says on any screen that the run did not finish. No verdict is shown for such a run. */
export function RunNotice({ runId }: { runId: string | null }) {
  const { data: run } = usePolling(() => api.getRun(runId ?? 'none'), 4000, true, [runId]);
  const kind = run?.notice?.kind;
  if (!run || (kind !== 'scan-incomplete' && kind !== 'docker-not-running')) return null;
  return <Banner kind={kind} detail={run.notice?.detail} />;
}
