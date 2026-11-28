import type { SVGProps } from 'react';

const base = { width: 20, height: 20, viewBox: '0 0 20 20', fill: 'none', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, style: { flex: 'none' } } as const;
type P = SVGProps<SVGSVGElement>;

export const IconShield = (p: P) => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1D4ED8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>
    <path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z" /><path d="M9 12l2 2 4-4" />
  </svg>
);
export const IconFlaky = (p: P) => (<svg {...base} stroke="#8A3A0B" {...p}><path d="M2 11l3.5-5 4 8 3-6 3.5 4" /></svg>);
export const IconReal = (p: P) => (<svg {...base} stroke="#8F1D14" {...p}><circle cx="10" cy="10" r="8" /><path d="M7 7l6 6M13 7l-6 6" /></svg>);
export const IconUnknown = (p: P) => (<svg {...base} stroke="#3B4048" {...p}><circle cx="10" cy="10" r="8" /><path d="M7.8 7.6a2.3 2.3 0 1 1 3.4 2c-.8.4-1.2.9-1.2 1.7M10 14v.01" /></svg>);
export const IconPolluter = (p: P) => (<svg {...base} stroke="#15171A" {...p}><path d="M10 2.5C8 5.8 5.5 8 5.5 11a4.5 4.5 0 0 0 9 0c0-3-2.5-5.2-4.5-8.5z" /></svg>);
export const IconClean = (p: P) => (<svg {...base} stroke="#4A4F57" {...p}><circle cx="10" cy="10" r="8" /><path d="M6.5 10.3l2.4 2.4 4.6-5" /></svg>);
export const IconInfo = (p: P) => (<svg {...base} stroke="currentColor" {...p}><circle cx="10" cy="10" r="8" /><path d="M10 9v5M10 6.2v.01" /></svg>);
export const IconWarn = (p: P) => (<svg {...base} stroke="currentColor" {...p}><path d="M10 3l8 14H2z" /><path d="M10 8v4M10 14.5v.01" /></svg>);
export const IconOk = (p: P) => (<svg {...base} stroke="currentColor" {...p}><circle cx="10" cy="10" r="8" /><path d="M6.5 10.3l2.4 2.4 4.6-5" /></svg>);

export const STATUS_ICON = {
  flaky: IconFlaky, real: IconReal, unknown: IconUnknown, polluter: IconPolluter, clean: IconClean,
} as const;
