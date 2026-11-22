import React, { useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { LayoutDashboard, Briefcase, ListTodo, Settings, Send, FileText, BarChart3, Inbox, Menu, X } from 'lucide-react';
import { usePipeline } from '../context/contexts';
import { Spinner } from './Feedback';

const LINKS = [
  ['/', 'Dashboard', LayoutDashboard, true],
  ['/jobs', 'Job Listings', Briefcase],
  ['/tracker', 'Tracker', ListTodo],
  ['/applications', 'Applications', Inbox],
  ['/analytics', 'Analytics', BarChart3],
  ['/resumes', 'Resumes', FileText],
  ['/settings', 'Settings', Settings],
];

// Small always-visible indicator while a job search runs (on every page); links back to the live panel.
const RunIndicator = ({ onNavigate }) => {
  const { running, progress } = usePipeline() || {};
  if (!running) return null;
  return (
    <Link to="/" className="run-indicator" onClick={onNavigate} title="A job search is running: open the Dashboard to see its progress">
      <Spinner size={14} label="Searching" />
      <span>Searching... {progress?.saved ? `${progress.saved} new` : progress?.stage_label || ''}</span>
    </Link>
  );
};

const Sidebar = () => {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  return (
    <nav className={`sidebar${open ? ' sidebar-open' : ''}`} aria-label="Main">
      <div className="sidebar-header">
        <Link to="/" className="brand" onClick={close}>
          <Send size={22} color="var(--primary)" aria-hidden="true" />
          <span>Autopilot</span>
        </Link>
        <RunIndicator onNavigate={close} />
        <button type="button" className="icon-btn menu-toggle" aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>
      <div className="sidebar-nav">
        {LINKS.map(([to, label, Icon, end]) => (
          <NavLink key={to} to={to} end={end} onClick={close}
            className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            <Icon size={20} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
};

export default Sidebar;
