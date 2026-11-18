import { NavLink } from 'react-router-dom';
import { IconShield } from './Icons';
import { USE_MOCK } from '../api/client';
import { useRun } from '../RunContext';

const LINKS = [
  { to: '/', label: 'Live', end: true },
  { to: '/findings', label: 'Findings' },
  { to: '/repo-map', label: 'Repo map' },
  { to: '/results', label: 'Results' },
];

export function Header({ right }: { right?: React.ReactNode }) {
  const { runId } = useRun();
  return (
    <header className="header">
      <div className="header-in">
        <div className="brand"><IconShield /> FlakeGuard</div>
        <nav className="nav" aria-label="Main">
          {LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => (isActive ? 'active' : '')}>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="header-right">
          {USE_MOCK && <span className="demo-badge" title="Every value on screen is built-in sample data">Demo data</span>}
          {runId && <span className="pill mono">{runId}</span>}
          {right}
        </div>
      </div>
    </header>
  );
}
