import React from 'react';
import { alsoFoundOn, formatScore, scoreClass, sourceMeta, STATUS_BADGE } from '../lib/format';

// Coloured badge for a job source; a career-board job shows its board (Greenhouse / Lever / Ashby).
export const SourceBadge = ({ source, url, title }) => {
  const meta = sourceMeta(source, url);
  return (
    <span className="badge source-badge" style={{ background: meta.bg, color: meta.fg }} title={title || `Found on ${meta.label}`}>
      {meta.label}
    </span>
  );
};

// "Also found on: Jooble, Adzuna" for jobs merged from several sources.
export const AlsoFoundOn = ({ job, compact = false }) => {
  const others = alsoFoundOn(job);
  if (!others.length) return null;
  return (
    <span className="also-found" title="The same job was listed on these sources too; duplicates were merged.">
      {compact ? '+ ' : 'Also found on: '}
      {others.map((s) => <SourceBadge key={s} source={s} />)}
    </span>
  );
};

export const ScoreBadge = ({ score, size = 'md' }) => (
  <span className={`score-pill ${scoreClass(score)} score-pill-${size}`} title={score == null ? 'Not scored' : `Match score ${formatScore(score)} / 10`}>
    {formatScore(score)}<span className="score-pill-max">/10</span>
  </span>
);

export const StatusBadge = ({ status }) => (
  <span className={`badge ${STATUS_BADGE[status] || 'badge-neutral'}`} title="Your own progress (tracker)">
    {status || 'To Apply'}
  </span>
);

const DECISION = {
  approved: { label: 'Approved', badge: 'badge-success' },
  skipped: { label: 'Not interested', badge: 'badge-neutral' },
  pending: { label: 'Awaiting your decision', badge: 'badge-warning' },
};

export const DecisionBadge = ({ status }) => {
  const d = DECISION[status || 'pending'] || DECISION.pending;
  return <span className={`badge ${d.badge}`} title="Approve / Not interested decision">{d.label}</span>;
};

export const NewTag = () => <span className="badge badge-new" title="Found by the latest job search">NEW</span>;
