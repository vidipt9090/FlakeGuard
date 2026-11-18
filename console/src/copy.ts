import type { ScreenState } from './types';

/** Intended wording for every unusual state. Never reword in components; edit here. */
export interface StateCopy {
  tone: 'neutral' | 'amber' | 'red' | 'blue';
  title: string;
  text: string;
  action: string | null;
  where: string;
}

export const STATE_COPY: Record<ScreenState, StateCopy> = {
  'first-run': {
    tone: 'neutral',
    title: 'Nothing scanned yet',
    text: 'Paste a repo or pick a pull request, then press Run scan.',
    action: 'Run scan',
    where: 'Live',
  },
  'actions-unavailable': {
    tone: 'amber',
    title: 'GitHub Actions cannot be reached',
    text: 'Running this scan on this machine instead. Docker isolation still applies if you chose it.',
    action: 'Try Actions again',
    where: 'Live',
  },
  'docker-not-running': {
    tone: 'red',
    title: 'Docker is not running',
    text: 'You asked for Docker isolation, so nothing was run. Start Docker Desktop, or untick Isolate in Docker.',
    action: 'Check again',
    where: 'Live',
  },
  'scan-incomplete': {
    tone: 'red',
    title: 'The scan stopped early',
    text: 'No verdict is shown because the run did not finish. Open the run on GitHub to see why.',
    action: 'Open run on GitHub',
    where: 'Live, post-merge',
  },
  'recorded-run': {
    tone: 'blue',
    title: 'This is a recorded run, not live',
    text: 'It was saved from an earlier real run. Values on screen are from that run.',
    action: 'Switch to live',
    where: 'All screens',
  },
  'no-findings': {
    tone: 'blue',
    title: 'No evidence of flakiness in 10 runs',
    text: 'This is not proof the tests are stable. More runs would narrow it further.',
    action: 'Run 10 more',
    where: 'Findings',
  },
  'quarantine-refused': {
    tone: 'red',
    title: 'Not quarantined',
    text: 'This test fails in 10 of 10 runs, so it looks like a real bug. Fix the code or the test instead.',
    action: 'Open the finding',
    where: 'Findings',
  },
  'post-merge': {
    tone: 'blue',
    title: 'No evidence of flakiness in 10 runs after this change',
    text: 'This is not proof it is fixed. The check looks again after every merge.',
    action: null,
    where: 'Live',
  },
  'ask-nothing': {
    tone: 'neutral',
    title: 'Nothing relevant found',
    text: 'No matching code was found, so there is no answer to give. Try naming a file or test.',
    action: null,
    where: 'Findings',
  },
};

export const STATUS_WORD: Record<string, string> = {
  flaky: 'Flaky',
  real: 'Real failure',
  unknown: 'Unknown',
  polluter: 'Polluter',
  clean: 'Clean',
};
